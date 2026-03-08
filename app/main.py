"""FastAPI application entry point."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.core.config import Config
from app.core.database import init_db, get_db
from app.api.routes import router
from app.services.whatsapp_monitor import WhatsAppMonitor
from app.services.pipeline import process_messages_batch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

whatsapp_monitor: WhatsAppMonitor | None = None
monitor_task: asyncio.Task | None = None


async def on_new_messages(messages: list[dict]):
    """Callback when WhatsApp monitor finds new messages."""
    logger.info(f"Processing {len(messages)} new messages")
    results = await process_messages_batch(messages)
    for r in results:
        logger.info(f"  Job {r.get('job_id')}: {r.get('status')} - {r.get('details', '')}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App startup and shutdown."""
    # Initialize
    init_db()
    Config.get()
    config = Config.get()
    logger.info("Database initialized, config loaded")
    logger.info(f"Mode: {config.mode}")
    logger.info(f"Monitoring groups: {config.whatsapp_groups}")
    logger.info(f"Scheduling: {config.scheduling}")

    # Initialize default settings
    with get_db() as db:
        defaults = {
            "whatsapp_status": "not_started",
            "initial_fetch_limit": str(config.scheduling["initial_fetch_limit"]),
            "recent_scan_limit": str(config.scheduling["recent_scan_limit"]),
            "polling_interval_seconds": str(config.scheduling["polling_interval_seconds"]),
            "first_run_recent_hours": str(config.scheduling["first_run_recent_hours"]),
        }
        for key, value in defaults.items():
            db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )

    yield

    # Shutdown
    global whatsapp_monitor, monitor_task
    if whatsapp_monitor:
        whatsapp_monitor.stop()
    if monitor_task:
        monitor_task.cancel()


app = FastAPI(
    title="Job Application Automation System",
    description="Automated job application system monitoring WhatsApp groups",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount static files
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Include routes
app.include_router(router)


# ─── WhatsApp Control Endpoints ──────────────────────────────

@app.post("/api/whatsapp/start")
async def start_whatsapp():
    """Start WhatsApp monitoring."""
    global whatsapp_monitor, monitor_task

    if monitor_task and not monitor_task.done():
        return {"status": "already_running"}

    whatsapp_monitor = WhatsAppMonitor()

    async def run_monitor():
        try:
            with get_db() as db:
                db.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES ('whatsapp_status', 'starting')"
                )
            await whatsapp_monitor.start_monitoring(on_new_messages=on_new_messages)
        except Exception as e:
            logger.error(f"WhatsApp monitor error: {e}")
            with get_db() as db:
                db.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES ('whatsapp_status', ?)",
                    (f"error: {e}",),
                )

    monitor_task = asyncio.create_task(run_monitor())

    # Update status
    with get_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('whatsapp_status', 'running')"
        )

    return {"status": "started"}


@app.post("/api/whatsapp/stop")
async def stop_whatsapp():
    """Stop WhatsApp monitoring."""
    global whatsapp_monitor, monitor_task

    if whatsapp_monitor:
        whatsapp_monitor.stop()
    if monitor_task:
        monitor_task.cancel()

    with get_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('whatsapp_status', 'stopped')"
        )

    return {"status": "stopped"}

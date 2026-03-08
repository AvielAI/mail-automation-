"""WhatsApp Web monitoring service using Playwright.

Implements scheduling rules:
- First run: read latest 50 messages per group, only auto-process last 24h
- Ongoing: poll every 120s, read latest 30 messages, process only new unseen
- Deduplication via message_hash + group + timestamp
"""

import asyncio
import hashlib
import logging
import re
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

from playwright.async_api import async_playwright, Browser, Page

from app.core.config import Config, DATA_DIR
from app.core.database import get_db

logger = logging.getLogger(__name__)

WHATSAPP_USER_DATA = DATA_DIR / "whatsapp_session"


def normalize_text(text: str) -> str:
    """Normalize message text for deduplication."""
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


class WhatsAppMonitor:
    """Monitors WhatsApp Web groups for new messages."""

    def __init__(self):
        self.config = Config.get()
        self.groups = self.config.whatsapp_groups
        self.scheduling = self.config.scheduling
        self.browser: Browser | None = None
        self.page: Page | None = None
        self.is_logged_in = False
        self._running = False
        self._first_run_done = False
        self._last_poll_time: str | None = None
        self._last_cycle_new_count: int = 0

    @staticmethod
    def message_hash(group: str, text: str, timestamp: str) -> str:
        normalized = normalize_text(text)
        raw = f"{group}|{normalized}|{timestamp}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _check_first_run_done(self) -> bool:
        with get_db() as db:
            row = db.execute(
                "SELECT value FROM settings WHERE key = 'first_run_completed'"
            ).fetchone()
            return row is not None and row[0] == "true"

    def _mark_first_run_done(self):
        with get_db() as db:
            db.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES ('first_run_completed', 'true', ?)",
                (datetime.now().isoformat(),),
            )

    def _update_poll_time(self):
        now = datetime.now().isoformat()
        self._last_poll_time = now
        next_poll = (datetime.now() + timedelta(seconds=self.scheduling["polling_interval_seconds"])).isoformat()
        with get_db() as db:
            db.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES ('last_poll_time', ?, ?)",
                (now, now),
            )
            db.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES ('next_poll_time', ?, ?)",
                (next_poll, now),
            )
            db.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES ('last_cycle_new_count', ?, ?)",
                (str(self._last_cycle_new_count), now),
            )

    def _is_duplicate(self, msg_hash: str, group: str) -> bool:
        """Check if message already exists for this group."""
        with get_db() as db:
            row = db.execute(
                "SELECT id FROM raw_messages WHERE message_hash = ? AND whatsapp_group = ?",
                (msg_hash, group),
            ).fetchone()
            return row is not None

    def _is_recent(self, timestamp_str: str) -> bool:
        """Check if a message timestamp is within the first_run_recent_hours window."""
        hours = self.scheduling.get("first_run_recent_hours", 24)
        cutoff = datetime.now() - timedelta(hours=hours)
        try:
            # Try parsing various timestamp formats
            for fmt in ["%Y-%m-%dT%H:%M:%S", "%H:%M", "%d/%m/%Y, %H:%M"]:
                try:
                    ts = datetime.strptime(timestamp_str.strip(), fmt)
                    # If only time, assume today
                    if fmt == "%H:%M":
                        ts = ts.replace(year=datetime.now().year, month=datetime.now().month, day=datetime.now().day)
                    return ts >= cutoff
                except ValueError:
                    continue
        except Exception:
            pass
        # If we can't parse timestamp, consider it potentially recent on first run
        return True

    def _store_message(
        self, group: str, sender: str, text: str, timestamp: str,
        msg_hash: str, is_historical: bool = False,
    ) -> int | None:
        """Store a new message in the database. Returns row ID or None if duplicate."""
        if self._is_duplicate(msg_hash, group):
            return None

        normalized = normalize_text(text)
        now = datetime.now().isoformat()

        with get_db() as db:
            cursor = db.execute(
                """INSERT INTO raw_messages
                   (message_hash, whatsapp_group, sender, message_text, normalized_text,
                    whatsapp_timestamp, timestamp, first_seen_at, is_historical)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (msg_hash, group, sender, text, normalized, timestamp, timestamp, now, int(is_historical)),
            )
            return cursor.lastrowid

    async def launch_browser(self):
        """Launch Playwright browser with persistent session."""
        WHATSAPP_USER_DATA.mkdir(parents=True, exist_ok=True)
        pw = await async_playwright().start()
        self.browser = await pw.chromium.launch_persistent_context(
            user_data_dir=str(WHATSAPP_USER_DATA),
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1400, "height": 900},
        )
        self.page = self.browser.pages[0] if self.browser.pages else await self.browser.new_page()

    async def open_whatsapp(self):
        """Navigate to WhatsApp Web."""
        await self.page.goto("https://web.whatsapp.com", wait_until="domcontentloaded")
        logger.info("Navigated to WhatsApp Web")

    async def wait_for_login(self, timeout_seconds: int = 120) -> bool:
        """Wait for user to scan QR code or detect existing session."""
        try:
            await self.page.wait_for_selector(
                'div[aria-label="Chat list"], div[data-testid="chat-list"]',
                timeout=timeout_seconds * 1000,
            )
            self.is_logged_in = True
            with get_db() as db:
                db.execute(
                    "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES ('whatsapp_status', 'logged_in', ?)",
                    (datetime.now().isoformat(),),
                )
            logger.info("WhatsApp Web session is active")
            return True
        except Exception:
            logger.warning("WhatsApp login timeout - QR scan needed")
            self.is_logged_in = False
            with get_db() as db:
                db.execute(
                    "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES ('whatsapp_status', 'qr_needed', ?)",
                    (datetime.now().isoformat(),),
                )
            return False

    async def navigate_to_group(self, group_name: str) -> bool:
        """Open a specific WhatsApp group by searching for it."""
        try:
            search_box = await self.page.wait_for_selector(
                'div[contenteditable="true"][data-tab="3"]',
                timeout=5000,
            )
            await search_box.click()
            await search_box.fill("")
            await self.page.keyboard.type(group_name, delay=50)
            await asyncio.sleep(1.5)

            group_el = await self.page.wait_for_selector(
                f'span[title="{group_name}"]',
                timeout=5000,
            )
            if group_el:
                await group_el.click()
                await asyncio.sleep(1)
                return True
        except Exception as e:
            logger.warning(f"Could not navigate to group '{group_name}': {e}")
        return False

    async def read_visible_messages(self, group_name: str, limit: int = 30) -> list[dict]:
        """Read currently visible messages from the open chat."""
        messages = []
        try:
            msg_elements = await self.page.query_selector_all(
                'div.message-in, div[data-testid="msg-container"]'
            )
            # Take only the last N messages
            for el in msg_elements[-limit:]:
                try:
                    text_el = await el.query_selector(
                        'span.selectable-text, div[data-testid="msg-text"]'
                    )
                    if not text_el:
                        continue
                    text = await text_el.inner_text()
                    if not text or len(text.strip()) < 10:
                        continue

                    # Try to get WhatsApp timestamp
                    time_el = await el.query_selector(
                        'span[data-testid="msg-time"], div[data-pre-plain-text]'
                    )
                    wa_timestamp = ""
                    if time_el:
                        wa_timestamp = await time_el.get_attribute("data-pre-plain-text") or await time_el.inner_text()

                    timestamp = wa_timestamp or datetime.now().isoformat()

                    # Try to get sender
                    sender_el = await el.query_selector(
                        'span[data-testid="author"], span._ahxt'
                    )
                    sender = ""
                    if sender_el:
                        sender = await sender_el.inner_text()

                    msg_hash = self.message_hash(group_name, text.strip(), timestamp)

                    messages.append({
                        "group": group_name,
                        "sender": sender,
                        "text": text.strip(),
                        "timestamp": timestamp,
                        "wa_timestamp": wa_timestamp,
                        "hash": msg_hash,
                    })
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"Error reading messages from {group_name}: {e}")
        return messages

    async def _clear_search(self):
        """Clear the search box after navigating to a group."""
        try:
            search_box = await self.page.query_selector(
                'div[contenteditable="true"][data-tab="3"]'
            )
            if search_box:
                await search_box.fill("")
            await self.page.keyboard.press("Escape")
        except Exception:
            pass
        await asyncio.sleep(0.5)

    async def do_first_run(self) -> list[dict]:
        """First run: read latest 50 messages per group.

        - Import all into SQLite
        - Only flag recent ones (last 24h) for processing
        - Mark older ones as historical
        """
        logger.info("=== FIRST RUN: Scanning latest messages from all groups ===")
        fetch_limit = self.scheduling.get("initial_fetch_limit", 50)
        new_messages = []

        for group_name in self.groups:
            if await self.navigate_to_group(group_name):
                # Scroll up to load more messages
                await self._scroll_to_load(fetch_limit)

                messages = await self.read_visible_messages(group_name, limit=fetch_limit)
                logger.info(f"First run: {len(messages)} messages read from '{group_name}'")

                for msg in messages:
                    is_recent = self._is_recent(msg.get("wa_timestamp", msg["timestamp"]))
                    is_historical = not is_recent

                    msg_id = self._store_message(
                        msg["group"], msg["sender"], msg["text"],
                        msg["timestamp"], msg["hash"],
                        is_historical=is_historical,
                    )
                    if msg_id and is_recent:
                        msg["id"] = msg_id
                        new_messages.append(msg)
                        logger.info(
                            f"[RECENT] New message from '{group_name}': {msg['text'][:60]}..."
                        )
                    elif msg_id and is_historical:
                        logger.info(
                            f"[HISTORICAL] Stored from '{group_name}': {msg['text'][:60]}..."
                        )

                await self._clear_search()

        self._mark_first_run_done()
        self._first_run_done = True
        self._last_cycle_new_count = len(new_messages)
        self._update_poll_time()

        logger.info(f"First run complete: {len(new_messages)} recent messages to process")
        return new_messages

    async def _scroll_to_load(self, target_count: int):
        """Scroll up in the chat to load more messages."""
        try:
            chat_container = await self.page.query_selector(
                'div[data-testid="conversation-panel-messages"], div._akbu'
            )
            if not chat_container:
                return

            for _ in range(5):  # Max 5 scroll attempts
                current = await self.page.query_selector_all(
                    'div.message-in, div[data-testid="msg-container"]'
                )
                if len(current) >= target_count:
                    break
                await self.page.keyboard.press("Home")
                await asyncio.sleep(1)
        except Exception as e:
            logger.debug(f"Scroll failed (non-critical): {e}")

    async def collect_new_messages(self) -> list[dict]:
        """Ongoing polling: cycle through all groups, collect only new unseen messages."""
        scan_limit = self.scheduling.get("recent_scan_limit", 30)
        new_messages = []

        for group_name in self.groups:
            if await self.navigate_to_group(group_name):
                messages = await self.read_visible_messages(group_name, limit=scan_limit)
                for msg in messages:
                    if not self._is_duplicate(msg["hash"], msg["group"]):
                        msg_id = self._store_message(
                            msg["group"], msg["sender"], msg["text"],
                            msg["timestamp"], msg["hash"],
                            is_historical=False,
                        )
                        if msg_id:
                            msg["id"] = msg_id
                            new_messages.append(msg)
                            logger.info(
                                f"New message from '{group_name}': {msg['text'][:80]}..."
                            )
                await self._clear_search()

        self._last_cycle_new_count = len(new_messages)
        self._update_poll_time()
        return new_messages

    async def start_monitoring(self, on_new_messages=None):
        """Main monitoring loop with first-run + ongoing polling."""
        self._running = True
        await self.launch_browser()
        await self.open_whatsapp()

        logged_in = await self.wait_for_login()
        if not logged_in:
            logger.error("Not logged in to WhatsApp Web. Please scan QR code.")
            return

        # Check if first run already completed
        self._first_run_done = self._check_first_run_done()

        if not self._first_run_done:
            # First run: scan initial batch
            new_msgs = await self.do_first_run()
            if new_msgs and on_new_messages:
                await on_new_messages(new_msgs)
        else:
            logger.info("First run already completed, starting ongoing polling")

        # Ongoing polling loop
        poll_interval = self.scheduling.get("polling_interval_seconds", 120)
        logger.info(f"Starting polling loop (interval={poll_interval}s)")

        with get_db() as db:
            db.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES ('whatsapp_status', 'monitoring', ?)",
                (datetime.now().isoformat(),),
            )

        while self._running:
            try:
                await asyncio.sleep(poll_interval)
                new_msgs = await self.collect_new_messages()
                if new_msgs and on_new_messages:
                    await on_new_messages(new_msgs)
                elif new_msgs:
                    logger.info(f"Collected {len(new_msgs)} new messages")
                else:
                    logger.debug("No new messages this cycle")
            except Exception as e:
                logger.error(f"Monitoring cycle error: {e}")

    def stop(self):
        self._running = False
        with get_db() as db:
            db.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES ('whatsapp_status', 'stopped', ?)",
                (datetime.now().isoformat(),),
            )

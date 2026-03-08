"""Configuration loader - loads all YAML files from config directory."""

import os
from pathlib import Path
from typing import Any

import yaml


CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
GENERATED_DIR = Path(__file__).resolve().parent.parent.parent / "generated"

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
GENERATED_DIR.mkdir(exist_ok=True)

DATABASE_PATH = DATA_DIR / "jobs.db"


def load_yaml(filename: str) -> dict[str, Any]:
    """Load a single YAML config file."""
    filepath = CONFIG_DIR / filename
    if not filepath.exists():
        raise FileNotFoundError(f"Config file not found: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class Config:
    """Central configuration holder."""

    _instance = None

    def __init__(self):
        self.candidate_profile = load_yaml("candidate_profile.yaml")
        self.master_cv = load_yaml("master_cv.yaml")
        self.job_matching = load_yaml("job_matching_brain.yaml")
        self.application_profiles = load_yaml("application_profiles.yaml")
        self.field_mapping = load_yaml("field_mapping.yaml")
        self.generated_files_schema = load_yaml("generated_files_schema.yaml")
        self.workflow_rules = load_yaml("workflow_rules.yaml")

    @classmethod
    def get(cls) -> "Config":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reload(cls) -> "Config":
        cls._instance = cls()
        return cls._instance

    @property
    def candidate(self) -> dict:
        return self.candidate_profile.get("candidate", {})

    @property
    def mode(self) -> str:
        return self.workflow_rules.get("workflow", {}).get("mode", "full_automatic")

    @property
    def whatsapp_groups(self) -> list[str]:
        return [
            "משרות טק: פיתוח תוכנה ג'וניורים 2",
            "תוכנה Lev job",
            "משרות טק: data ג'וניורים 2",
            "הנדסת תעשייה וניהול Lev job",
            "4 חיפוש משרות עבור ג'וניורים עם דנה פרנקל",
            "משרות הייטק חרדים ירושלים",
        ]

    @property
    def poll_interval(self) -> int:
        return (
            self.workflow_rules.get("workflow", {})
            .get("monitoring", {})
            .get("poll_interval_seconds", 120)
        )

    @property
    def scheduling(self) -> dict:
        """Scheduling and sync defaults."""
        return {
            "initial_fetch_limit": 50,
            "recent_scan_limit": 30,
            "polling_interval_seconds": 120,
            "first_run_recent_hours": 24,
        }

    @property
    def email_settings(self) -> dict:
        return {
            "sender_email": os.environ.get("SENDER_EMAIL", self.candidate.get("email", "")),
            "sender_password": os.environ.get("SENDER_EMAIL_PASSWORD", ""),
            "smtp_server": os.environ.get("SMTP_SERVER", "smtp.gmail.com"),
            "smtp_port": int(os.environ.get("SMTP_PORT", "587")),
        }

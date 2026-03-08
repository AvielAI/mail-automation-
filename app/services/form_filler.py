"""Automated form filling service using Playwright."""

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright, Page, ElementHandle

from app.core.config import Config
from app.core.database import get_db
from app.models.job import ExtractedJob

logger = logging.getLogger(__name__)


class FormFiller:
    """Fills job application forms automatically using Playwright."""

    def __init__(self):
        self.config = Config.get()
        self.field_mapping = self.config.field_mapping.get("field_mapping", {})
        self.personal_fields = self.field_mapping.get("personal", [])
        self.file_upload_fields = self.field_mapping.get("file_upload", [])
        self.high_risk_fields = self.field_mapping.get("high_risk_fields", [])
        self.filled_fields: list[dict] = []
        self.risky_fields: list[dict] = []
        self.blocked = False
        self.block_reason = ""

    def _get_candidate_value(self, value_path: str) -> str:
        """Resolve a dotted value path against candidate config."""
        parts = value_path.split(".")
        data = self.config.candidate_profile
        for part in parts:
            if isinstance(data, dict):
                data = data.get(part, "")
            else:
                return ""
        return str(data) if data else ""

    def _check_high_risk(self, field_name: str, field_label: str) -> dict | None:
        """Check if a field is high-risk and should cause a pause."""
        combined = f"{field_name} {field_label}".lower()
        for risk in self.high_risk_fields:
            patterns = risk.get("patterns", [])
            for pattern in patterns:
                if pattern.lower() in combined:
                    return {
                        "action": risk.get("action", "pause"),
                        "reason": risk.get("reason", "High-risk field detected"),
                    }
        return None

    def _find_matching_value(self, field_name: str, field_label: str) -> tuple[str, float]:
        """Find a value for a form field from the field mapping.

        Returns (value, confidence).
        """
        combined = f"{field_name} {field_label}".lower()

        for mapping in self.personal_fields:
            selectors = mapping.get("selectors", [])
            for selector in selectors:
                if selector.lower() in combined:
                    value = self._get_candidate_value(mapping["value_path"])
                    if value:
                        return value, 0.9
        return "", 0.0

    async def fill_form(
        self,
        page: Page,
        job: ExtractedJob,
        resume_paths: dict,
        cover_letter_paths: dict | None = None,
        job_id: int | None = None,
    ) -> dict:
        """Fill all form fields on the current page.

        Returns status dict with filled_fields, risky_fields, blocked, etc.
        """
        self.filled_fields = []
        self.risky_fields = []
        self.blocked = False
        self.block_reason = ""

        # Check for CAPTCHA
        if await self._detect_captcha(page):
            self.blocked = True
            self.block_reason = "CAPTCHA detected"
            return self._result(job_id)

        # Find all input fields
        inputs = await page.query_selector_all(
            'input:not([type="hidden"]):not([type="submit"]):not([type="button"]), '
            "textarea, "
            'select, '
            'div[contenteditable="true"]'
        )

        for inp in inputs:
            try:
                await self._process_field(inp, page, job, resume_paths, cover_letter_paths)
            except Exception as e:
                logger.warning(f"Error processing field: {e}")

            if self.blocked:
                break

        # Store form answers in DB
        if job_id:
            self._save_form_answers(job_id)

        return self._result(job_id)

    async def _process_field(
        self, element: ElementHandle, page: Page,
        job: ExtractedJob, resume_paths: dict,
        cover_letter_paths: dict | None,
    ):
        """Process a single form field."""
        tag = await element.evaluate("el => el.tagName.toLowerCase()")
        field_type = await element.get_attribute("type") or ""
        field_name = await element.get_attribute("name") or ""
        field_id = await element.get_attribute("id") or ""
        field_placeholder = await element.get_attribute("placeholder") or ""
        field_label = await self._get_field_label(element, page)

        identifier = f"{field_name} {field_id} {field_placeholder} {field_label}"

        # Check for file upload
        if field_type == "file":
            await self._handle_file_upload(element, identifier, resume_paths, cover_letter_paths)
            return

        # Check high risk
        risk = self._check_high_risk(field_name, identifier)
        if risk:
            self.risky_fields.append({
                "field_name": field_name or field_id,
                "field_label": field_label,
                "risk_reason": risk["reason"],
            })
            if risk["action"] == "pause":
                self.blocked = True
                self.block_reason = risk["reason"]
            return

        # Try to find a matching value
        value, confidence = self._find_matching_value(field_name, identifier)

        if not value:
            # Check if field is required
            is_required = await element.get_attribute("required") is not None
            aria_required = await element.get_attribute("aria-required")
            if is_required or aria_required == "true":
                self.risky_fields.append({
                    "field_name": field_name or field_id,
                    "field_label": field_label,
                    "risk_reason": "Required field with no matching value",
                })
            return

        # Fill the field
        try:
            if tag == "select":
                await element.select_option(label=value)
            elif tag == "textarea" or tag == "div":
                await element.fill(value)
            else:
                await element.fill(value)

            self.filled_fields.append({
                "field_name": field_name or field_id,
                "field_label": field_label,
                "field_type": field_type or tag,
                "filled_value": value,
                "confidence": confidence,
            })
            logger.info(f"Filled field '{field_name or field_id}' with '{value[:30]}...' (conf={confidence})")
        except Exception as e:
            logger.warning(f"Could not fill field '{field_name}': {e}")

    async def _handle_file_upload(
        self, element: ElementHandle, identifier: str,
        resume_paths: dict, cover_letter_paths: dict | None,
    ):
        """Handle file upload fields."""
        id_lower = identifier.lower()

        # Determine which file to upload
        file_path = None
        for mapping in self.file_upload_fields:
            selectors = mapping.get("selectors", [])
            for sel in selectors:
                if sel.lower() in id_lower:
                    file_type = mapping.get("file_type", "resume")
                    prefer = mapping.get("prefer", "pdf")
                    fallback = mapping.get("fallback", "docx")

                    paths = resume_paths if file_type == "resume" else (cover_letter_paths or {})
                    file_path = paths.get(prefer) or paths.get(fallback)
                    break
            if file_path:
                break

        # Default to resume PDF/DOCX
        if not file_path:
            file_path = resume_paths.get("pdf") or resume_paths.get("docx")

        if file_path and Path(file_path).exists():
            try:
                await element.set_input_files(file_path)
                self.filled_fields.append({
                    "field_name": "file_upload",
                    "field_label": identifier[:50],
                    "field_type": "file",
                    "filled_value": str(file_path),
                    "confidence": 0.95,
                })
                logger.info(f"Uploaded file: {file_path}")
            except Exception as e:
                logger.error(f"File upload failed: {e}")
                self.blocked = True
                self.block_reason = f"File upload failure: {e}"
        else:
            logger.warning("No valid file found for upload")

    async def _get_field_label(self, element: ElementHandle, page: Page) -> str:
        """Try to find the label for a form field."""
        try:
            field_id = await element.get_attribute("id")
            if field_id:
                label = await page.query_selector(f'label[for="{field_id}"]')
                if label:
                    return await label.inner_text()
            # Try parent label
            parent_label = await element.evaluate(
                "el => el.closest('label')?.textContent || ''"
            )
            if parent_label:
                return parent_label.strip()
        except Exception:
            pass
        return ""

    async def _detect_captcha(self, page: Page) -> bool:
        """Detect CAPTCHA elements on the page."""
        captcha_selectors = [
            'iframe[src*="recaptcha"]',
            'iframe[src*="captcha"]',
            'div.g-recaptcha',
            'div[data-sitekey]',
            '#captcha',
            '.captcha',
        ]
        for sel in captcha_selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    return True
            except Exception:
                continue
        return False

    async def submit_form(self, page: Page) -> bool:
        """Submit the form if all required fields are confidently filled."""
        if self.blocked:
            logger.warning(f"Cannot submit - blocked: {self.block_reason}")
            return False

        try:
            # Look for submit button
            submit_selectors = [
                'button[type="submit"]',
                'input[type="submit"]',
                'button:has-text("Submit")',
                'button:has-text("Apply")',
                'button:has-text("שלח")',
                'button:has-text("הגש")',
            ]
            for sel in submit_selectors:
                btn = await page.query_selector(sel)
                if btn:
                    await btn.click()
                    await asyncio.sleep(2)
                    logger.info("Form submitted successfully")
                    return True

            logger.warning("No submit button found")
            return False
        except Exception as e:
            logger.error(f"Form submission error: {e}")
            return False

    def _save_form_answers(self, job_id: int):
        """Save filled form answers to database."""
        with get_db() as db:
            for field in self.filled_fields:
                db.execute(
                    """INSERT INTO form_answers
                       (job_id, field_name, field_selector, field_type, filled_value, confidence, is_risky, status)
                       VALUES (?, ?, ?, ?, ?, ?, 0, 'filled')""",
                    (job_id, field["field_name"], field.get("field_label", ""),
                     field["field_type"], field["filled_value"], field["confidence"]),
                )
            for field in self.risky_fields:
                db.execute(
                    """INSERT INTO form_answers
                       (job_id, field_name, field_selector, field_type, filled_value, confidence, is_risky, status)
                       VALUES (?, ?, ?, ?, ?, 0, 1, 'risky')""",
                    (job_id, field["field_name"], field.get("field_label", ""),
                     "unknown", field.get("risk_reason", ""), 0),
                )

    def _result(self, job_id: int | None) -> dict:
        return {
            "filled_count": len(self.filled_fields),
            "risky_count": len(self.risky_fields),
            "blocked": self.blocked,
            "block_reason": self.block_reason,
            "filled_fields": self.filled_fields,
            "risky_fields": self.risky_fields,
        }


async def fill_and_submit_form(
    url: str,
    job: ExtractedJob,
    resume_paths: dict,
    cover_letter_paths: dict | None = None,
    job_id: int | None = None,
) -> dict:
    """Open URL, fill form, and submit. Returns result dict."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, channel="chrome")
        context = await browser.new_context()
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            filler = FormFiller()
            result = await filler.fill_form(page, job, resume_paths, cover_letter_paths, job_id)

            submitted = False
            if not result["blocked"]:
                submitted = await filler.submit_form(page)
                await asyncio.sleep(3)

            result["submitted"] = submitted
            result["url"] = url

            # Update job status
            if job_id:
                status = "submitted" if submitted else ("blocked" if result["blocked"] else "form_filled")
                with get_db() as db:
                    db.execute(
                        "UPDATE jobs SET submission_status = ?, apply_method = 'form', notes = COALESCE(notes, '') || ? WHERE id = ?",
                        (status, f" | Form fill: {result['filled_count']} fields, blocked={result['blocked']}", job_id),
                    )
                    db.execute(
                        "INSERT INTO job_runs (job_id, stage, status, finished_at, details) VALUES (?, ?, ?, ?, ?)",
                        (job_id, "form_fill", status, datetime.now().isoformat(), str(result)),
                    )

            return result
        except Exception as e:
            logger.error(f"Form fill error for {url}: {e}")
            if job_id:
                with get_db() as db:
                    db.execute(
                        "UPDATE jobs SET submission_status = 'blocked', notes = COALESCE(notes, '') || ? WHERE id = ?",
                        (f" | Form error: {e}", job_id),
                    )
                    db.execute(
                        "INSERT INTO errors (job_id, stage, error_type, error_message) VALUES (?, ?, ?, ?)",
                        (job_id, "form_fill", "form_error", str(e)),
                    )
            return {"blocked": True, "block_reason": str(e), "filled_count": 0, "submitted": False}
        finally:
            await browser.close()

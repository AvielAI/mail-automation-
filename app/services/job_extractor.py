"""Extract structured job details from raw message text."""

import logging
import re

from app.models.job import ExtractedJob
from app.services.job_classifier import EMAIL_REGEX, URL_REGEX, PHONE_REGEX

logger = logging.getLogger(__name__)

# Common job title patterns (Hebrew + English)
TITLE_PATTERNS = [
    r"(?:דרוש[הים]*|מחפשים|looking for|hiring)\s*[:\-–]?\s*(.+?)(?:\n|$)",
    r"(?:משרת?|position|role)\s*[:\-–]?\s*(.+?)(?:\n|$)",
    r"(?:תפקיד)\s*[:\-–]?\s*(.+?)(?:\n|$)",
]

COMPANY_PATTERNS = [
    r"(?:חברת?|company|at|ב[-–]?)\s*[:\-–]?\s*([A-Za-z\u0590-\u05FF][\w\s\u0590-\u05FF]{1,40})(?:\n|,|$)",
]

LOCATION_PATTERNS = [
    r"(?:מיקום|location|אזור|ב[-–]?)\s*[:\-–]?\s*([\w\s\u0590-\u05FF]{2,30})(?:\n|,|$)",
    r"(?:ירושלים|תל[- ]?אביב|חיפה|באר[- ]?שבע|רמת[- ]?גן|הרצליה|פתח[- ]?תקוה|נתניה|ראשון לציון|remote|hybrid)",
]

JOB_TYPE_PATTERNS = [
    r"(?:full[- ]?time|משרה מלאה)",
    r"(?:part[- ]?time|משרה חלקית)",
    r"(?:hybrid|היברידי)",
    r"(?:remote|עבודה מרחוק|מהבית)",
    r"(?:freelance|פרילנס)",
]


def extract_first_match(patterns: list[str], text: str) -> str:
    """Try multiple patterns and return first match."""
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            # Return the captured group if it exists, else full match
            result = match.group(1) if match.lastindex else match.group(0)
            return result.strip()
    return ""


def extract_all_matches(patterns: list[str], text: str) -> list[str]:
    """Extract all matches from patterns."""
    results = []
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
        results.extend(matches)
    return results


def extract_email(text: str) -> str:
    match = EMAIL_REGEX.search(text)
    return match.group(0) if match else ""


def extract_link(text: str) -> str:
    match = URL_REGEX.search(text)
    return match.group(0) if match else ""


def extract_phone(text: str) -> str:
    match = PHONE_REGEX.search(text)
    return match.group(0) if match else ""


def extract_requirements(text: str) -> str:
    """Extract requirements section from the message."""
    # Look for requirements header
    req_patterns = [
        r"(?:דרישות|requirements?|skills?|ניסיון נדרש)\s*[:\-–]?\s*\n((?:[-•*–]\s*.+\n?)+)",
        r"(?:דרישות|requirements?)\s*[:\-–]?\s*(.+?)(?:\n\n|\Z)",
    ]
    for pattern in req_patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()

    # Fallback: collect bullet point lines
    lines = text.split("\n")
    bullet_lines = [
        line.strip() for line in lines
        if line.strip().startswith(("-", "•", "*", "–"))
    ]
    if bullet_lines:
        return "\n".join(bullet_lines)
    return ""


def extract_job_details(text: str, group_name: str = "") -> ExtractedJob:
    """Extract structured job information from raw message text."""
    job = ExtractedJob()
    job.raw_message = text
    job.whatsapp_group = group_name

    # Extract fields
    job.job_title = extract_first_match(TITLE_PATTERNS, text)
    job.company = extract_first_match(COMPANY_PATTERNS, text)
    job.location = extract_first_match(LOCATION_PATTERNS, text)
    job.apply_email = extract_email(text)
    job.apply_link = extract_link(text)
    job.apply_phone = extract_phone(text)
    job.requirements = extract_requirements(text)
    job.description = text[:500]  # First 500 chars as description

    # Detect job type
    job_types = extract_all_matches(JOB_TYPE_PATTERNS, text)
    job.job_type = ", ".join(set(job_types)) if job_types else ""

    # If no title found, try first non-empty line
    if not job.job_title:
        for line in text.strip().split("\n"):
            line = line.strip()
            if len(line) > 5 and len(line) < 100:
                job.job_title = line
                break

    logger.info(
        f"Extracted job: title='{job.job_title}', company='{job.company}', "
        f"email='{job.apply_email}', link='{job.apply_link}'"
    )
    return job

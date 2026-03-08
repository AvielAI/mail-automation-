"""Two-stage job detection: rule-based filter + LLM classification."""

import json
import logging
import re

from app.models.job import DetectionResult

logger = logging.getLogger(__name__)

# Stage 1: Rule-based signals
STRONG_POSITIVE_KEYWORDS = [
    r"דרוש[הים]*",
    r"מחפשים",
    r"משרה",
    r'קו"ח',
    r"קורות חיים",
    r"ניסיון",
    r"דרישות",
    r"יתרון",
    r"לשלוח",
    r"\bapply\b",
    r"\bposition\b",
    r"\bjob\b",
    r"\brequirements?\b",
    r"\bresume\b",
    r"\bcv\b",
    r"\bfull[- ]?time\b",
    r"\bhybrid\b",
    r"\bremote\b",
]

ROLE_KEYWORDS = [
    r"analyst",
    r"developer",
    r"engineer",
    r"automation",
    r"\bdata\b",
    r"\bpmo\b",
    r"system",
    r"מפתח",
    r"מהנדס",
    r"אנליסט",
    r"מנהל פרויקטים",
]

STRONG_NEGATIVE_KEYWORDS = [
    r"^תודה[.!]?$",
    r"^בהצלחה[.!]?$",
    r"^מעוניין\??$",
    r"^אפשר פרטים\??$",
    r"^הקפצה$",
    r"^שאלה כללית$",
]

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
URL_REGEX = re.compile(
    r"https?://[^\s<>\"']+|www\.[^\s<>\"']+",
    re.IGNORECASE,
)
PHONE_REGEX = re.compile(r"0\d{1,2}[-.\s]?\d{3}[-.\s]?\d{4}|\+972[-.\s]?\d{1,2}[-.\s]?\d{3}[-.\s]?\d{4}")


def stage1_rule_filter(text: str) -> DetectionResult:
    """Fast rule-based filter for job detection."""
    text_lower = text.lower().strip()
    signals = []
    positive_score = 0
    negative_score = 0

    # Check for very short messages (likely chat noise)
    if len(text_lower) < 30:
        # Short messages are almost never job posts
        for pattern in STRONG_NEGATIVE_KEYWORDS:
            if re.search(pattern, text_lower):
                return DetectionResult(
                    is_job_post=False,
                    is_actionable=False,
                    confidence=10,
                    reason="Short message with negative signal",
                    detected_signals=["short_message", "negative_keyword"],
                )
        if len(text_lower) < 15:
            return DetectionResult(
                is_job_post=False,
                is_actionable=False,
                confidence=5,
                reason="Very short message",
                detected_signals=["very_short"],
            )

    # Check negative signals
    for pattern in STRONG_NEGATIVE_KEYWORDS:
        if re.search(pattern, text_lower):
            negative_score += 30

    # Check positive keywords
    for pattern in STRONG_POSITIVE_KEYWORDS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            positive_score += 10
            signals.append(f"keyword:{pattern}")

    # Check role keywords
    for pattern in ROLE_KEYWORDS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            positive_score += 8
            signals.append(f"role:{pattern}")

    # Check for email
    if EMAIL_REGEX.search(text):
        positive_score += 15
        signals.append("email")

    # Check for URL
    if URL_REGEX.search(text):
        positive_score += 12
        signals.append("url")

    # Check for phone
    if PHONE_REGEX.search(text):
        positive_score += 5
        signals.append("phone")

    # Calculate confidence
    net_score = max(0, positive_score - negative_score)
    confidence = min(100, net_score)

    # Determine result
    if confidence >= 80:
        return DetectionResult(
            is_job_post=True,
            is_actionable=True,
            confidence=confidence,
            reason="Strong positive signals from rule-based filter",
            detected_signals=signals,
        )
    elif confidence >= 50:
        return DetectionResult(
            is_job_post=True,
            is_actionable=False,  # Needs LLM confirmation
            confidence=confidence,
            reason="Moderate signals - needs LLM confirmation",
            detected_signals=signals,
        )
    elif confidence >= 20:
        # Uncertain - needs LLM
        return DetectionResult(
            is_job_post=False,
            is_actionable=False,
            confidence=confidence,
            reason="Weak signals - needs LLM classification",
            detected_signals=signals,
        )
    else:
        return DetectionResult(
            is_job_post=False,
            is_actionable=False,
            confidence=confidence,
            reason="No significant job signals detected",
            detected_signals=signals,
        )


def stage2_llm_classify(text: str) -> DetectionResult:
    """LLM-based classification for uncertain messages.

    This is a placeholder - requires an LLM API key to function.
    Falls back to enhanced rule-based analysis.
    """
    # Enhanced rule-based fallback when no LLM is configured
    result = stage1_rule_filter(text)

    # Additional heuristics for borderline cases
    lines = text.strip().split("\n")
    line_count = len(lines)

    # Multi-line messages with structure are more likely jobs
    if line_count >= 5:
        result.confidence = min(100, result.confidence + 15)
    elif line_count >= 3:
        result.confidence = min(100, result.confidence + 8)

    # Messages with bullet points or dashes often list requirements
    bullet_lines = sum(1 for line in lines if line.strip().startswith(("-", "•", "*", "–")))
    if bullet_lines >= 2:
        result.confidence = min(100, result.confidence + 12)
        result.detected_signals.append("structured_list")

    # Re-evaluate based on adjusted confidence
    if result.confidence >= 80:
        result.is_job_post = True
        result.is_actionable = True
        result.reason = "Classified as actionable job post (enhanced analysis)"
    elif result.confidence >= 50:
        result.is_job_post = True
        result.is_actionable = False
        result.reason = "Likely job post - sent to review queue"

    return result


def classify_message(text: str) -> DetectionResult:
    """Main classification entry point with 2-stage pipeline."""
    # Stage 1
    result = stage1_rule_filter(text)

    if result.confidence >= 80:
        logger.info(f"Stage 1: Confident job post (conf={result.confidence})")
        return result

    if result.confidence < 20:
        logger.info(f"Stage 1: Not a job post (conf={result.confidence})")
        return result

    # Stage 2: LLM / enhanced analysis for uncertain cases
    logger.info(f"Stage 1 uncertain (conf={result.confidence}), running Stage 2")
    result = stage2_llm_classify(text)
    logger.info(f"Stage 2 result: conf={result.confidence}, actionable={result.is_actionable}")
    return result

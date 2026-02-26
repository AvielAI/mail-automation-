"""Regex-based field parsers for Hebrew + English insurance documents."""
from __future__ import annotations

import re
from typing import Optional

from app.utils.helpers import parse_date, safe_float, mask_id_number

# ---------------------------------------------------------------------------
# Compiled pattern sets
# ---------------------------------------------------------------------------

# Policy number
_POLICY_PATTERNS = [
    re.compile(r"(?:מספר פוליסה|פוליסה מס[\"'`\s]*|policy\s*(?:no|number|#)[.:]*)\s*[:\-]?\s*(\d[\d\-]{4,20})", re.IGNORECASE),
    re.compile(r"(?:policy)\s*[:\-]?\s*(\d{6,15})", re.IGNORECASE),
    re.compile(r"פוליסה[:\s]*(\d{6,15})"),
]

# Insurer name
_INSURER_PATTERNS = [
    re.compile(r"(?:חברת ביטוח|חברה)[:\s]+([\u0590-\u05FF\w\s]{3,40})", re.IGNORECASE),
    re.compile(r"(?:insurer|insurance company|insured by)[:\s]+([\w\s,\.]{3,50})", re.IGNORECASE),
    re.compile(r"(מגדל|הכשרה|הראל|כלל|מנורה|הפניקס|שירביט|ביטוח ישיר|AIG|אליאנץ|ציון|הסנה)", re.IGNORECASE),
]

# Insured name
_INSURED_PATTERNS = [
    re.compile(r"(?:שם מבוטח|מבוטח|insured(?:\s+name)?)[:\s]+([\u0590-\u05FF\w\s]{2,40})", re.IGNORECASE),
    re.compile(r"(?:policy\s*holder)[:\s]+([\w\s]{2,40})", re.IGNORECASE),
]

# ID number (Israeli 9-digit or passport)
_ID_PATTERNS = [
    re.compile(r"(?:ת\.?ז\.?|מספר זהות|id\s*(?:no|number)?)[:\s]*(\d{7,9})", re.IGNORECASE),
    re.compile(r"\b(\d{9})\b"),
]

# Date ranges — start/end
_DATE_RANGE_PATTERNS = [
    re.compile(
        r"(?:תקופת ביטוח|תוקף|period\s*of\s*insurance|coverage\s*period)[:\s]*"
        r"(\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4})\s*(?:עד|[-–—]|to)\s*"
        r"(\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4})",
        re.IGNORECASE,
    ),
]
_START_DATE_PATTERNS = [
    re.compile(r"(?:תחילת ביטוח|תחילה|start\s*date|inception)[:\s]*(\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4})", re.IGNORECASE),
    re.compile(r"(?:from)[:\s]+(\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4})", re.IGNORECASE),
]
_END_DATE_PATTERNS = [
    re.compile(r"(?:תאריך סיום|תום|expiry\s*date|end\s*date)[:\s]*(\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4})", re.IGNORECASE),
    re.compile(r"(?:to|until|through)[:\s]+(\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4})", re.IGNORECASE),
]
_RENEWAL_PATTERNS = [
    re.compile(r"(?:תאריך חידוש|חידוש|renewal\s*date)[:\s]*(\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4})", re.IGNORECASE),
]

# Premium
_PREMIUM_PATTERNS = [
    # Monthly
    re.compile(r"(?:פרמיה חודשית|דמי ביטוח חודשי|monthly\s*premium)[:\s]*(?:₪|ils|nis|usd|\$)?\s*([\d,\.]+)", re.IGNORECASE),
    # Yearly
    re.compile(r"(?:פרמיה שנתית|דמי ביטוח שנתי|annual\s*premium|yearly\s*premium)[:\s]*(?:₪|ils|nis|usd|\$)?\s*([\d,\.]+)", re.IGNORECASE),
    # Generic premium
    re.compile(r"(?:פרמיה|דמי ביטוח|premium)[:\s]*(?:₪|ils|nis|usd|\$)?\s*([\d,\.]+)", re.IGNORECASE),
]
_AMOUNT_DUE_PATTERNS = [
    re.compile(r"(?:לתשלום|סכום לתשלום|amount\s*due|total\s*due)[:\s]*(?:₪|ils|nis|\$)?\s*([\d,\.]+)", re.IGNORECASE),
]

# Currency
_CURRENCY_PATTERNS = [
    re.compile(r"\b(₪|nis|ils)\b", re.IGNORECASE),
    re.compile(r"\b(usd|\$|eur|€|gbp|£)\b", re.IGNORECASE),
]

# Vehicle
_VEHICLE_PATTERNS = [
    re.compile(r"(?:מספר רכב|לוחית|vehicle\s*(?:no|number|reg)|registration)[:\s]*([A-Z0-9\-]{4,10})", re.IGNORECASE),
    re.compile(r"\b(\d{2,3}-\d{2,3}-\d{2,3})\b"),   # Israeli plate
]

# Property address
_ADDRESS_PATTERNS = [
    re.compile(r"(?:כתובת הנכס|הנכס|property\s*address)[:\s]+([\u0590-\u05FF\w\s,\.]{5,60})", re.IGNORECASE),
]

# Agent
_AGENT_PATTERNS = [
    re.compile(r"(?:שם הסוכן|agent\s*name)[:\s]+([\u0590-\u05FF\w\s]{2,40})", re.IGNORECASE),
]
_AGENCY_PATTERNS = [
    re.compile(r"(?:סוכנות ביטוח|agency\s*name?)[:\s]+([\u0590-\u05FF\w\s]{2,50})", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Public extractor
# ---------------------------------------------------------------------------

def extract_fields(text: str) -> dict:
    """Apply all patterns to *text* and return a flat dict of extracted fields."""
    results: dict = {}

    results["policy_number"] = _first_match(_POLICY_PATTERNS, text)
    results["insurer_company"] = _first_match(_INSURER_PATTERNS, text)
    results["insured_name"] = _first_match(_INSURED_PATTERNS, text)

    id_raw = _first_match(_ID_PATTERNS, text)
    results["id_number_masked"] = mask_id_number(id_raw) if id_raw else ""

    # Dates
    date_range = _date_range(text)
    results["start_date"] = date_range[0] or _first_date(_START_DATE_PATTERNS, text)
    results["end_date"] = date_range[1] or _first_date(_END_DATE_PATTERNS, text)
    results["renewal_date"] = _first_date(_RENEWAL_PATTERNS, text)

    # Premium
    monthly, yearly = _extract_premiums(text)
    results["premium_monthly"] = monthly
    results["premium_yearly"] = yearly
    results["premium_monthly_derived"] = False
    results["premium_yearly_derived"] = False

    # Derive missing premium
    if monthly is None and yearly is not None:
        results["premium_monthly"] = round(yearly / 12, 2)
        results["premium_monthly_derived"] = True
    elif yearly is None and monthly is not None:
        results["premium_yearly"] = round(monthly * 12, 2)
        results["premium_yearly_derived"] = True

    results["amount_due"] = safe_float(_first_match(_AMOUNT_DUE_PATTERNS, text) or "")
    results["currency"] = _extract_currency(text)

    results["vehicle_number"] = _first_match(_VEHICLE_PATTERNS, text)
    results["property_address"] = _first_match(_ADDRESS_PATTERNS, text)
    results["agent_name"] = _first_match(_AGENT_PATTERNS, text)
    results["agency_name"] = _first_match(_AGENCY_PATTERNS, text)

    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _first_match(patterns: list[re.Pattern], text: str) -> str:
    for pat in patterns:
        m = pat.search(text)
        if m:
            return m.group(1).strip()
    return ""


def _first_date(patterns: list[re.Pattern], text: str) -> str:
    raw = _first_match(patterns, text)
    return parse_date(raw) if raw else ""


def _date_range(text: str) -> tuple[str, str]:
    for pat in _DATE_RANGE_PATTERNS:
        m = pat.search(text)
        if m:
            return parse_date(m.group(1)) or "", parse_date(m.group(2)) or ""
    return "", ""


def _extract_premiums(text: str) -> tuple[Optional[float], Optional[float]]:
    monthly: Optional[float] = None
    yearly: Optional[float] = None

    # Try labelled monthly
    for pat in [
        re.compile(r"(?:פרמיה חודשית|monthly\s*premium)[:\s]*(?:₪|ils|nis|usd|\$)?\s*([\d,\.]+)", re.IGNORECASE),
    ]:
        m = pat.search(text)
        if m:
            monthly = safe_float(m.group(1))
            break

    # Try labelled yearly
    for pat in [
        re.compile(r"(?:פרמיה שנתית|annual\s*premium|yearly\s*premium)[:\s]*(?:₪|ils|nis|usd|\$)?\s*([\d,\.]+)", re.IGNORECASE),
    ]:
        m = pat.search(text)
        if m:
            yearly = safe_float(m.group(1))
            break

    # Generic fallback
    if monthly is None and yearly is None:
        for pat in [
            re.compile(r"(?:פרמיה|דמי ביטוח|premium)[:\s]*(?:₪|ils|nis|usd|\$)?\s*([\d,\.]+)", re.IGNORECASE),
        ]:
            m = pat.search(text)
            if m:
                val = safe_float(m.group(1))
                if val and val > 500:   # heuristic: large number → yearly
                    yearly = val
                elif val:
                    monthly = val
                break

    return monthly, yearly


def _extract_currency(text: str) -> str:
    for pat in _CURRENCY_PATTERNS:
        m = pat.search(text)
        if m:
            raw = m.group(1).upper()
            mapping = {"₪": "ILS", "NIS": "ILS", "ILS": "ILS",
                       "$": "USD", "USD": "USD",
                       "€": "EUR", "EUR": "EUR",
                       "£": "GBP", "GBP": "GBP"}
            return mapping.get(raw, raw)
    return "ILS"  # default for Israeli documents

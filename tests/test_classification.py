"""Tests for classification and field extraction."""
import pytest

from app.models.entities import ExtractedDoc, GmailMessageMeta, InsuranceType
from app.services.classification_service import classify_and_extract, _classify
from app.services.extraction.parsers import extract_fields


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def test_classify_car_english():
    ins_type, conf = _classify("This is your car insurance policy renewal.")
    assert ins_type == InsuranceType.CAR.value
    assert conf > 0.3


def test_classify_health_hebrew():
    ins_type, conf = _classify("ביטוח בריאות תרופות ניתוח אשפוז")
    assert ins_type == InsuranceType.HEALTH.value
    assert conf > 0.3


def test_classify_home():
    ins_type, conf = _classify("home insurance building contents property address")
    assert ins_type == InsuranceType.HOME.value


def test_classify_life():
    ins_type, conf = _classify("ביטוח חיים ריסק פטירה שארים")
    assert ins_type == InsuranceType.LIFE.value


def test_classify_travel():
    ins_type, conf = _classify("travel insurance abroad trip")
    assert ins_type == InsuranceType.TRAVEL.value


def test_classify_unknown():
    ins_type, conf = _classify("hello world nothing relevant here")
    assert ins_type == InsuranceType.UNKNOWN.value
    assert conf == 0.0


def test_classify_empty_text():
    ins_type, conf = _classify("")
    assert ins_type == InsuranceType.UNKNOWN.value


# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------

def test_extract_policy_number_english():
    text = "Policy Number: 123456789"
    fields = extract_fields(text)
    assert fields["policy_number"] == "123456789"


def test_extract_policy_number_hebrew():
    text = "מספר פוליסה: 987654321"
    fields = extract_fields(text)
    assert fields["policy_number"] == "987654321"


def test_extract_insurer_known_name():
    text = "מגדל ביטוח - תנאי הפוליסה"
    fields = extract_fields(text)
    assert "מגדל" in fields["insurer_company"]


def test_extract_date_range():
    text = "תקופת ביטוח: 01/01/2024 עד 31/12/2024"
    fields = extract_fields(text)
    assert fields["start_date"] == "2024-01-01"
    assert fields["end_date"] == "2024-12-31"


def test_extract_premium_monthly():
    text = "פרמיה חודשית: ₪ 350.00"
    fields = extract_fields(text)
    assert fields["premium_monthly"] == 350.0
    # Annual should be derived
    assert fields["premium_yearly"] == pytest.approx(350.0 * 12, rel=0.01)
    assert fields["premium_yearly_derived"] is True


def test_extract_premium_yearly():
    text = "annual premium: 6000"
    fields = extract_fields(text)
    assert fields["premium_yearly"] == 6000.0
    assert fields["premium_monthly"] == pytest.approx(500.0, rel=0.01)
    assert fields["premium_monthly_derived"] is True


def test_extract_vehicle_number_israeli_plate():
    text = "מספר רכב: 123-456-789"
    fields = extract_fields(text)
    assert "123" in (fields["vehicle_number"] or "")


def test_extract_currency_ils():
    text = "דמי ביטוח: 500 ₪"
    fields = extract_fields(text)
    assert fields["currency"] == "ILS"


def test_extract_id_number_masked():
    text = "ת.ז.: 123456789"
    fields = extract_fields(text)
    assert fields["id_number_masked"].endswith("6789")
    assert fields["id_number_masked"].startswith("*")


# ---------------------------------------------------------------------------
# End-to-end classify_and_extract
# ---------------------------------------------------------------------------

def _make_meta(**kwargs) -> GmailMessageMeta:
    defaults = dict(
        message_id="test_msg_001",
        subject="ביטוח רכב - חידוש פוליסה",
        sender="insurance@example.com",
        date="Thu, 01 Jan 2024 10:00:00 +0000",
        snippet="חידוש פוליסה רכב",
    )
    defaults.update(kwargs)
    return GmailMessageMeta(**defaults)


def _make_doc(text: str, source: str = "body") -> ExtractedDoc:
    return ExtractedDoc(raw_text=text, source=source)


def test_classify_and_extract_car_record():
    meta = _make_meta(subject="ביטוח רכב")
    doc = _make_doc("מספר פוליסה: 111222333\nפרמיה חודשית: 300\nחברת ביטוח: מגדל\nרכב מכונית אוטו")
    records = classify_and_extract(meta, [doc])
    assert len(records) == 1
    rec = records[0]
    assert rec.insurance_type == InsuranceType.CAR.value
    assert rec.policy_number == "111222333"
    assert rec.premium_monthly == 300.0
    assert "מגדל" in rec.insurer_company


def test_classify_and_extract_sets_needs_review_when_low_confidence():
    # Explicitly clear snippet so default car snippet doesn't influence classification
    meta = _make_meta(subject="fwd: something", snippet="")
    doc = _make_doc("random text without any insurance keywords at all abcdefg")
    records = classify_and_extract(meta, [doc])
    assert len(records) == 1
    assert records[0].needs_review is True


def test_classify_and_extract_message_id_set():
    meta = _make_meta(message_id="specific_msg_id")
    doc = _make_doc("ביטוח בריאות policy number 555")
    records = classify_and_extract(meta, [doc])
    assert records[0].message_id == "specific_msg_id"

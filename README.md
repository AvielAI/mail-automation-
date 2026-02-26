# Insurance Mail to Excel

A production-ready Flask web application that connects to Gmail via OAuth2, finds insurance-related emails (Hebrew + English), extracts structured data from bodies and PDF attachments, and exports a structured Excel workbook — with **no database**.

Designed for deployment on **Render Free** tier with ephemeral filesystem.

---

## Features

- **Gmail OAuth2** — read-only access, no password collected
- **Hebrew + English** insurance email detection
- **PDF extraction** — PyMuPDF + pdfplumber, OCR fallback (pytesseract)
- **Classification** — 8 insurance types with confidence score
- **Field extraction** — policy number, insurer, dates, premiums, vehicle #, address, agent, and more
- **Excel export** — 4-sheet workbook (All Policies, Monthly Payments, Needs Review, Sync Log)
- **No database** — file-based JSON persistence, ephemeral-friendly
- **Bootstrap UI** — Dashboard, Sync, Records, Review, Export, Errors/Logs

---

## Quick Start (local)

```bash
# 1. Clone and install
git clone <repo>
cd <repo>
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env: fill GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, FLASK_SECRET_KEY

# 3. Run dev server
flask --app wsgi:app run --debug

# 4. Open http://localhost:5000 → Connect Gmail → Sync → Export
```

### Google OAuth2 setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials
2. Create an **OAuth 2.0 Client ID** (type: Web application)
3. Add authorised redirect URI: `http://localhost:5000/auth/callback`
   (for production: `https://your-app.onrender.com/auth/callback`)
4. Copy **Client ID** and **Client Secret** into `.env`

---

## Deploy to Render

1. Fork/push this repo to GitHub
2. In Render dashboard: **New → Web Service** → connect repo
3. Render picks up `render.yaml` automatically
4. Set environment variables in Render dashboard:
   - `GOOGLE_CLIENT_ID`
   - `GOOGLE_CLIENT_SECRET`
   - `GOOGLE_REDIRECT_URI` = `https://your-app.onrender.com/auth/callback`
5. Add the production redirect URI to your Google OAuth2 client

> **Note:** Render Free filesystem is ephemeral. Data stored in `/tmp/insurance_data` is wiped on restart. Reconnect Gmail and re-sync if data disappears.

---

## Project Structure

```
.
├── app/
│   ├── __init__.py          # create_app factory
│   ├── config.py            # Config class from env vars
│   ├── models/
│   │   └── entities.py      # Dataclasses: InsuranceRecord, etc.
│   ├── routes/
│   │   ├── main.py          # Dashboard, /healthz, /records, /review, /errors
│   │   ├── auth.py          # Gmail OAuth2 connect/callback/disconnect
│   │   ├── sync.py          # Sync trigger + status polling
│   │   └── export.py        # Excel download
│   ├── services/
│   │   ├── gmail_service.py          # Gmail API search + attachment fetch
│   │   ├── classification_service.py # Type classification + field extraction
│   │   ├── dedup_service.py          # Record deduplication
│   │   ├── excel_export_service.py   # openpyxl workbook builder
│   │   ├── extraction/
│   │   │   ├── pdf_extractor.py      # PyMuPDF + pdfplumber + OCR dispatch
│   │   │   ├── ocr_extractor.py      # pytesseract + pdf2image
│   │   │   └── parsers.py            # Regex field parsers (He+En)
│   │   └── storage/
│   │       ├── base.py               # Storage facade
│   │       ├── file_store.py         # Path management
│   │       ├── atomic_io.py          # Atomic JSON/text writes
│   │       ├── locks.py              # File-based sync lock
│   │       └── repositories.py       # Record/Error/SyncLog repos
│   ├── templates/           # Jinja2 + Bootstrap 5
│   └── utils/helpers.py
├── tests/
│   ├── test_storage.py
│   ├── test_classification.py
│   ├── test_extraction.py
│   └── test_excel.py
├── wsgi.py
├── render.yaml
├── gunicorn.conf.py
├── requirements.txt
├── .env.example
└── SECURITY_NOTES.md
```

---

## Running Tests

```bash
pip install pytest pytest-mock
pytest tests/ -v
```

---

## Supported Insurance Types

| Code | Hebrew | English |
|------|--------|---------|
| `car` | ביטוח רכב | Car/Vehicle |
| `health` | ביטוח בריאות | Health/Medical |
| `home` | ביטוח דירה | Home/Property |
| `life` | ביטוח חיים | Life |
| `travel` | ביטוח נסיעות | Travel |
| `mortgage` | ביטוח משכנתא | Mortgage-related |
| `disability` | אובדן כושר | Disability/Loss of capacity |
| `other` / `unknown` | אחר | Other/Unknown |

---

## Extracted Fields

Policy number, insurer company, insured name, ID (masked last 4), start/end/renewal dates, monthly/annual premiums (with derivation flag), currency, amount due, payment frequency, vehicle number, property address, agent/agency name, source email metadata, extraction confidence, classification confidence, needs-review flag.

---

## Data Flow

```
Gmail API → Search messages → Download bodies + attachments
         → PDF/OCR text extraction
         → Rule-based classification (8 types)
         → Regex field extraction (He+En)
         → InsuranceRecord dataclass
         → JSON file persistence (ephemeral-safe)
         → Excel workbook on demand
```

---

## Security

See [SECURITY_NOTES.md](SECURITY_NOTES.md) for full details.

- Gmail read-only scope only
- ID numbers masked (last 4 digits)
- No logging of raw document text or tokens
- HttpOnly + Secure session cookies
- All secrets via environment variables

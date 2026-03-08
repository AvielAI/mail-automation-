# Job Application Automation System

A local Windows-based system that monitors WhatsApp Web groups for job postings and automatically applies to them.

## Features

- **WhatsApp Monitoring**: Monitors specified WhatsApp Web groups for new job posts using Playwright
- **Job Detection**: 2-stage pipeline (rule-based + enhanced analysis) to classify messages as actionable job posts
- **Resume Generation**: Auto-generates tailored DOCX and PDF resumes from source-of-truth YAML files
- **Form Filling**: Automatically fills online application forms using Playwright
- **Email Applications**: Sends application emails with resume attached when only an email address is available
- **Dashboard**: Local web dashboard to track all jobs, review blocked ones, and export reports
- **Export**: Export job data to Excel (.xlsx) and Word (.docx) reports
- **Scheduling**: Smart first-run behavior (latest 50 messages, 24h window), continuous polling every 120s

## Mode

Default mode: **full_automatic** - processes jobs end-to-end automatically, pausing only on true blockers (CAPTCHA, 2FA, broken pages, missing mandatory data).

## Prerequisites

- Python 3.12+
- LibreOffice (for PDF conversion) - [Download](https://www.libreoffice.org/download/)
- Google Chrome browser
- Gmail App Password (for sending emails)

## Windows Setup Instructions

### 1. Clone and navigate to project

```cmd
cd Desktop\My_Project
```

### 2. Create virtual environment

```cmd
python -m venv venv
venv\Scripts\activate
```

### 3. Install dependencies

```cmd
pip install -r requirements.txt
```

### 4. Install Playwright browsers

```cmd
playwright install chromium
```

### 5. Configure environment

```cmd
copy .env.example .env
```

Edit `.env` and set your Gmail App Password:
- Go to https://myaccount.google.com/apppasswords
- Generate an App Password for "Mail"
- Paste it in `.env` as `SENDER_EMAIL_PASSWORD`

### 6. Edit your profile data

Edit these YAML files in the `config/` folder with your real information:

- `config/candidate_profile.yaml` - Your personal details, education, languages
- `config/master_cv.yaml` - Your work experience, projects, skills, certifications

**Important**: The system never invents data. It only uses what you put in these files.

### 7. Start the application

```cmd
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 8. Open the dashboard

Open your browser and go to: http://127.0.0.1:8000

### 9. Start WhatsApp monitoring

1. Click "Start Monitor" on the dashboard
2. WhatsApp Web will open in a Chrome window
3. Scan the QR code with your phone (first time only)
4. The system will start monitoring the configured groups

## Scheduling Behavior

### First Run
- Reads only the latest 50 messages per group
- Only auto-processes messages from the last 24 hours
- Older messages stored as historical records (can be reprocessed manually)

### Ongoing Polling
- Polls every 120 seconds
- Reads latest 30 messages per group per cycle
- Only processes new unseen messages
- Deduplication via message hash + group + timestamp

### Dashboard Monitoring
- Shows last polling time, next polling time
- First run completed status
- New messages found in last cycle

## Project Structure

```
/app
  /api          - FastAPI routes and endpoints
  /core         - Configuration and database
  /services     - All business logic services
  /models       - Data models
  /templates    - Jinja2 HTML templates
  /static       - CSS and JavaScript
  /utils        - Utility functions
/config         - YAML configuration files (source of truth)
/data           - SQLite database and WhatsApp session (auto-created)
/generated      - Generated resumes, cover letters, exports (auto-created)
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard |
| `/job/{id}` | GET | Job detail page |
| `/blocked` | GET | Blocked/review jobs |
| `/sent` | GET | Sent/submitted jobs |
| `/api/jobs` | GET | List jobs (JSON) |
| `/api/jobs/{id}` | GET | Job details (JSON) |
| `/api/jobs/{id}/retry` | POST | Retry a failed job |
| `/api/jobs/{id}/approve` | POST | Approve a review job |
| `/api/process-text` | POST | Process a message manually |
| `/api/whatsapp/start` | POST | Start WhatsApp monitor |
| `/api/whatsapp/stop` | POST | Stop WhatsApp monitor |
| `/api/export/excel` | GET | Export to Excel |
| `/api/export/word` | GET | Export to Word |
| `/api/status` | GET | System status |

## Monitored WhatsApp Groups

1. משרות טק: פיתוח תוכנה ג'וניורים 2
2. תוכנה Lev job
3. משרות טק: data ג'וניורים 2
4. הנדסת תעשייה וניהול Lev job
5. חיפוש משרות עבור ג'וניורים עם דנה פרנקל 4
6. משרות הייטק חרדים ירושלים

## Application Routing

- **Has application link**: Opens and fills the form, uploads resume, submits automatically
- **Has only email**: Sends a professional application email with resume attached

## Blocking Conditions

The system pauses only on:
- CAPTCHA / reCAPTCHA
- 2FA / login required
- Broken page / failed load
- Missing mandatory data not in YAML
- Unknown high-risk fields (salary, ID number)
- File upload failure

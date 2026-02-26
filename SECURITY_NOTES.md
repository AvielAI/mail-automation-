# Security Notes

## Overview

This application handles sensitive personal insurance data. This document summarises the security controls in place and known limitations on the Render Free tier.

---

## Secrets Management

- **No secrets in code**: All credentials (`FLASK_SECRET_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`) are loaded exclusively from environment variables.
- **Render env vars**: Set via the Render dashboard as `sync: false` (not committed to the repo). Never commit `.env` files with real values.
- **`.env.example`**: Contains only placeholder values; do not fill in real credentials.

---

## OAuth2 / Gmail

- Uses Google OAuth2 **read-only** scope (`gmail.readonly`). The app never requests write, send, or delete permissions.
- OAuth access tokens and refresh tokens are stored in `DATA_DIR/state/oauth_tokens.json` on the ephemeral filesystem. On Render Free this is `/tmp` — erased on restart.
- Tokens are **never logged**. The log redacts credential fields.
- Session cookies are `HttpOnly=True`, `SameSite=Lax`, and `Secure=True` in production (set via `SESSION_COOKIE_SECURE=true` env var).
- Flask `SECRET_KEY` is auto-generated per deployment by Render (`generateValue: true`).

---

## PII Handling

- **ID numbers** (Israeli Teudat Zehut / passport): extracted from documents, but only the last 4 digits are stored and displayed (`id_number_masked`). The full ID is never persisted.
- **Names and addresses**: stored in JSON files on ephemeral disk; erased on restart.
- **Raw extracted text** (from PDFs/OCR) is stored as an optional cache in `extracted_text/`. These files may contain PII. On ephemeral Render Free they are not permanent; on persistent storage, restrict filesystem access.
- Logs do **not** include raw document text, full ID numbers, or access tokens.

---

## Input Validation

- `custom_query` form input passed to the Gmail API search is used directly via the official `google-api-python-client`. It is not passed to a shell or SQL engine and poses no injection risk in the current implementation.
- All other user inputs are rendered via Jinja2 auto-escaping (XSS protection).

---

## HTTP Security

- Production deployments should be HTTPS-only (Render provides TLS automatically).
- CSRF: The sync form uses a simple POST; for higher security, add a CSRF token (Flask-WTF). Currently acceptable as the app is single-user (connected to your own Gmail).
- No user registration or authentication layer beyond OAuth2 — the app assumes the person who connected Gmail is the only user.

---

## Dependencies

- All dependencies are pinned in `requirements.txt`. Run `pip audit` or `safety check` regularly to detect known CVEs.
- PyMuPDF, pdfplumber, and pytesseract operate on **untrusted** PDF/image content from external emails. These libraries have had security vulnerabilities historically. Keep them up to date.
- PDF parsing is done in-process; a malicious PDF could potentially exploit parsing bugs. Consider sandboxing or a separate worker for higher-risk deployments.

---

## Data Persistence & Ephemeral FS

- On Render Free, all data is stored under `/tmp/insurance_data` and is **ephemeral** — wiped on restart/redeploy.
- No sensitive data is sent to any third party other than Google APIs.
- Attachments are cached locally during a sync run only.

---

## Recommendations for Production Hardening

1. Add Flask-WTF CSRF protection.
2. Add rate limiting (e.g., Flask-Limiter) on OAuth and sync endpoints.
3. Move to persistent storage (Render persistent disk or object storage) for multi-restart reliability.
4. Implement proper user authentication if serving multiple users.
5. Consider running PDF/image parsing in a sandboxed subprocess.
6. Enable Content-Security-Policy headers.
7. Rotate `FLASK_SECRET_KEY` on credential compromise.

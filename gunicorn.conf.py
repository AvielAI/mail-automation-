"""Gunicorn configuration for production (Render Free)."""
import os

# Explicitly declare the WSGI app so gunicorn never falls back to 'app:app'
# when it detects an 'app/' package directory in the project root.
wsgi_app = "wsgi:app"

bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
workers = int(os.environ.get('WEB_CONCURRENCY', '2'))
threads = int(os.environ.get('GUNICORN_THREADS', '4'))
timeout = 120
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = "info"
worker_class = "gthread"
max_requests = 1000
max_requests_jitter = 100

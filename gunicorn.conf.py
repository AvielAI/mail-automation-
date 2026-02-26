"""Gunicorn configuration for production (Render Free)."""
import os

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

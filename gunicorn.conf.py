"""Gunicorn конфигурация для production.

Переменные окружения, которые можно переопределить:
  GUNICORN_WORKERS  — число воркеров (по умолчанию: 2*CPU+1, мин 2, макс 8)
  GUNICORN_THREADS  — потоков на воркер (по умолчанию 2)
  GUNICORN_TIMEOUT  — таймаут воркера в секундах (по умолчанию 60)
  PORT              — порт (по умолчанию 5000)
"""

import multiprocessing
import os

# ── Binding ───────────────────────────────────────────────────────────────────
port = os.environ.get("PORT", "5000")
bind = f"0.0.0.0:{port}"

# ── Workers ───────────────────────────────────────────────────────────────────
_cpu = multiprocessing.cpu_count()
_default_workers = max(2, min(2 * _cpu + 1, 8))
workers = int(os.environ.get("GUNICORN_WORKERS", _default_workers))
threads = int(os.environ.get("GUNICORN_THREADS", 2))
worker_class = "sync"

# ── Timeouts ──────────────────────────────────────────────────────────────────
timeout = int(os.environ.get("GUNICORN_TIMEOUT", 60))
graceful_timeout = 30
keepalive = 5

# ── Logging ───────────────────────────────────────────────────────────────────
accesslog = "-"  # stdout
errorlog = "-"  # stderr
loglevel = os.environ.get("LOG_LEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s %(D)sµs'

# ── Security ──────────────────────────────────────────────────────────────────
# Не принимать слишком большие заголовки (защита от slowloris и header injection)
limit_request_line = 8190
limit_request_fields = 100
limit_request_field_size = 8190

# ── Process naming ────────────────────────────────────────────────────────────
proc_name = "investtrack"

# ── Pre-loading ───────────────────────────────────────────────────────────────
# preload_app = True  # включить если нет APScheduler (иначе дублирует джобы)

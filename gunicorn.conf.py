"""Gunicorn конфигурация для production.

Переменные окружения, которые можно переопределить:
  GUNICORN_WORKERS  — число воркеров (по умолчанию: 2, макс 4)
  GUNICORN_THREADS  — потоков на воркер (по умолчанию 4)
  GUNICORN_TIMEOUT  — таймаут воркера в секундах (по умолчанию 60)
  PORT              — порт (по умолчанию 5000)
"""

import multiprocessing
import os

# ── Binding ───────────────────────────────────────────────────────────────────
port = os.environ.get("PORT", "5000")
bind = f"0.0.0.0:{port}"

# ── Workers ───────────────────────────────────────────────────────────────────
# На сервере с 2 GB RAM держим максимум 2 воркера.
# gthread: один процесс + N потоков — значительно меньше памяти, чем sync.
_cpu = multiprocessing.cpu_count()
_default_workers = max(1, min(_cpu, 2))
workers = int(os.environ.get("GUNICORN_WORKERS", _default_workers))
threads = int(os.environ.get("GUNICORN_THREADS", 4))
worker_class = "gthread"

# ── Timeouts ──────────────────────────────────────────────────────────────────
timeout = int(os.environ.get("GUNICORN_TIMEOUT", 60))
graceful_timeout = 30
keepalive = 5

# ── Logging ───────────────────────────────────────────────────────────────────
accesslog = "-"  # stdout
errorlog = "-"   # stderr
loglevel = os.environ.get("LOG_LEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s %(D)sµs'

# ── Security ──────────────────────────────────────────────────────────────────
limit_request_line = 8190
limit_request_fields = 100
limit_request_field_size = 8190

# ── Process naming ────────────────────────────────────────────────────────────
proc_name = "investtrack"

# ── Pre-loading ───────────────────────────────────────────────────────────────
# preload_app = False: каждый воркер загружает приложение независимо.
# Это позволяет файловому замку в app.py работать корректно:
# первый стартовавший воркер захватывает замок и запускает APScheduler,
# остальные замок не получают и планировщик не дублируют.

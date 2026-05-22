# ── Stage 1: install deps ────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /install
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/deps -r requirements.txt

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /deps /usr/local

# Copy application source
COPY . .

# Create avatar upload dir
RUN mkdir -p static/avatars

ENV FLASK_ENV=production \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 5000

# Run migrations then start Gunicorn
CMD ["sh", "-c", "python scripts/init_db.py && gunicorn --workers 4 --threads 2 --bind 0.0.0.0:5000 --timeout 60 app:app"]

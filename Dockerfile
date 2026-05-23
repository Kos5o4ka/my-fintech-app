# ── Stage 1: builder — компиляция зависимостей ────────────────────────────────
# Устанавливаем пакеты в отдельном слое, чтобы не тащить gcc и dev-заголовки
# в финальный образ (экономит ~200 МБ).
FROM python:3.10-slim AS builder

WORKDIR /build

# Системные зависимости для компиляции psycopg2 и Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        libjpeg-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/deps -r requirements.txt


# ── Stage 2: runtime — финальный образ ───────────────────────────────────────
FROM python:3.10-slim AS runtime

LABEL org.opencontainers.image.title="InvestTrack" \
      org.opencontainers.image.description="Flask bond portfolio tracker with MOEX integration"

WORKDIR /app

# Только runtime shared libs (без компилятора и dev-заголовков)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        libjpeg62-turbo \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Пакеты из builder-стадии
COPY --from=builder /deps /usr/local

# Исходный код
COPY . .

# Переменные окружения
ENV FLASK_ENV=production \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Директории для загрузок и кэша; непривилегированный пользователь
RUN mkdir -p static/avatars static/uploads .cache \
    && adduser --disabled-password --gecos '' --uid 1000 appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 5000

# Docker HEALTHCHECK — используем /health из blueprints/main.py
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# Запуск через gunicorn с настройками из gunicorn.conf.py
CMD ["sh", "-c", "flask db upgrade && gunicorn --config gunicorn.conf.py app:app"]

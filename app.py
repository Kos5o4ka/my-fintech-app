import atexit
import logging
import os
from datetime import datetime, timezone

# ── Sentry (опционально) ──────────────────────────────────────────────────────
# Активируется только если задана переменная SENTRY_DSN.
# Перехватывает необработанные исключения и отправляет в Sentry.io.
if os.environ.get("SENTRY_DSN"):
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=os.environ["SENTRY_DSN"],
            integrations=[
                FlaskIntegration(transaction_style="url"),
                SqlalchemyIntegration(),
            ],
            # Трассировка производительности — 10% запросов (настройте под нагрузку)
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES_RATE", "0.1")),
            # Не отправлять личные данные пользователей (IP, cookies)
            send_default_pii=False,
            environment=os.environ.get("FLASK_ENV", "development"),
        )
    except ImportError:
        pass  # sentry-sdk не установлен — продолжаем без него

from flask import Flask, request, jsonify, render_template, session
from flask_cors import CORS
from flask_login import current_user, logout_user
from flask_wtf import CSRFProtect
from flask_wtf.csrf import generate_csrf
from werkzeug.exceptions import RequestEntityTooLarge

from config import get_config
from extensions import db, login_manager, migrate, cache, limiter, mail
from models import User

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(get_config())

# ── Extensions ────────────────────────────────────────────────────────────────
db.init_app(app)
login_manager.init_app(app)
migrate.init_app(app, db)

# Кэш: Redis (если REDIS_URL задан) → FileSystemCache (по умолчанию).
# FileSystemCache хранит данные на диске, не потребляет RAM, работает
# между воркерами Gunicorn — идеально для одного сервера с ограниченной памятью.
if app.config.get("REDIS_URL"):
    _cache_config = {
        "CACHE_TYPE": "RedisCache",
        "CACHE_REDIS_URL": app.config["REDIS_URL"],
    }
else:
    _cache_config = {
        "CACHE_TYPE": "FileSystemCache",
        "CACHE_DIR": os.path.join(app.root_path, ".cache"),
        "CACHE_THRESHOLD": 1000,          # макс. кол-во записей
        "CACHE_DEFAULT_TIMEOUT": 300,
    }
cache.init_app(app, config=_cache_config)
mail.init_app(app)
csrf = CSRFProtect()
csrf.init_app(app)
limiter.init_app(app)

CORS(app, supports_credentials=True, origins=app.config["CORS_ORIGINS"])


# ── Blueprints ────────────────────────────────────────────────────────────────
from blueprints.main import main_bp
from blueprints.auth import auth_bp
from blueprints.admin import admin_bp
from blueprints.profile import profile_bp
from blueprints.portfolio import portfolio_bp
from blueprints.telegram_bot import telegram_bp

app.register_blueprint(main_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(profile_bp)
app.register_blueprint(portfolio_bp)
app.register_blueprint(telegram_bp)

# Освобождаем webhook от CSRF-защиты (Telegram Bot API не отправляет CSRF)
csrf.exempt(telegram_bp)


# ── Idle timeout: сбрасываем сессию после 30 мин бездействия ─────────────────
@app.before_request
def enforce_idle_timeout():
    """Разлогиниваем пользователя если он не активен дольше IDLE_TIMEOUT_SECONDS."""
    if not current_user.is_authenticated:
        return

    idle_timeout = app.config.get("IDLE_TIMEOUT_SECONDS", 1800)
    now = datetime.now(timezone.utc).timestamp()
    last_active = session.get("_last_active", now)

    if now - last_active > idle_timeout:
        logout_user()
        session.clear()
        # Для API возвращаем 401, для страниц — ничего (Flask-Login перенаправит)
        if request.path.startswith("/api/"):
            return jsonify({
                "status": "error",
                "code": 401,
                "message": "Сессия истекла из-за неактивности. Войдите снова.",
            }), 401
        return

    session["_last_active"] = now


# ── Security headers (after every response) ───────────────────────────────────
@app.after_request
def set_security_headers(response):
    try:
        token = generate_csrf()
        response.set_cookie("XSRF-TOKEN", token, httponly=False, samesite="Lax")
    except Exception:
        pass

    # Убираем Server-заголовок (не раскрываем версию сервера)
    response.headers.remove("Server")

    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "geolocation=(), camera=(), microphone=(), payment=()",
    )
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self' cdn.jsdelivr.net 'unsafe-inline'; "
        "style-src 'self' cdn.jsdelivr.net 'unsafe-inline'; "
        "img-src 'self' data: ui-avatars.com; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'",
    )

    # HSTS — только для production (HTTPS-only)
    if not app.debug and not app.testing:
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )

    return response


# ── User loader ───────────────────────────────────────────────────────────────
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ── Error handlers ────────────────────────────────────────────────────────────
@app.errorhandler(400)
@app.errorhandler(401)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(413)
@app.errorhandler(500)
def handle_api_errors(error):
    if (
        request.path.startswith("/api/")
        or request.headers.get("Content-Type") == "application/json"
    ):
        message = (
            error.description if hasattr(error, "description") else "Внутренняя ошибка сервера"
        )
        if isinstance(error, RequestEntityTooLarge):
            message = "Загруженный файл слишком велик. Максимальный размер — 5 МБ."
        response_body = {
            "status": "error",
            "code": error.code if hasattr(error, "code") else 500,
            "message": message,
        }
        return jsonify(response_body), response_body["code"]

    if isinstance(error, RequestEntityTooLarge):
        return (
            render_template(
                "error.html",
                title="Файл слишком большой",
                message="Загруженный файл превышает допустимый размер 5 МБ.",
            ),
            413,
        )
    return error


# ── APScheduler: background price refresh ────────────────────────────────────
def _update_bond_prices() -> None:
    """Обновляет last_price всех активных облигаций через bulk UPDATE (один запрос)."""
    with app.app_context():
        try:
            from models import BondPortfolio
            from moex import get_moex_bond
            from constants import MOEX_BOND_TTL

            active = BondPortfolio.query.filter_by(is_sold=False).all()
            if not active:
                return

            # 1) Собираем уникальные ISINы и запрашиваем MOEX
            seen: dict[str, dict | None] = {}
            for bond in active:
                if bond.isin not in seen:
                    seen[bond.isin] = get_moex_bond(bond.isin)
                    if seen[bond.isin]:
                        try:
                            cache.set(f"moex_bond:{bond.isin}", seen[bond.isin], timeout=MOEX_BOND_TTL)
                        except Exception:
                            pass

            # 2) Bulk UPDATE — один SQL вместо N отдельных UPDATE
            mappings = [
                {"id": bond.id, "last_price": seen[bond.isin]["price"]}
                for bond in active
                if seen.get(bond.isin)
            ]
            if mappings:
                db.session.bulk_update_mappings(BondPortfolio, mappings)
                db.session.commit()

            logger.info(
                "Price update: %d ISINs, %d bonds updated",
                len([v for v in seen.values() if v]),
                len(mappings),
            )
        except Exception as exc:
            logger.error("Price update job failed: %s", exc)


def _send_coupon_reminders() -> None:
    """Рассылает напоминания о купонах завтра — через email и/или Telegram."""
    with app.app_context():
        has_tg = bool(app.config.get("TELEGRAM_BOT_TOKEN"))
        if not has_tg:
            return
        try:
            from models import User, BondPortfolio
            from moex import get_coupon_calendar
            from datetime import date, timedelta
            from services.telegram_service import send_message as tg_send

            tomorrow = date.today() + timedelta(days=1)

            # Собираем пользователей с Telegram-каналом уведомлений
            users = User.query.filter(
                db.and_(User.telegram_chat_id.isnot(None), User.telegram_notifications == True)
            ).all()

            for user in users:
                bonds = BondPortfolio.query.filter_by(user_id=user.id, is_sold=False).all()
                due = []
                for bond in bonds:
                    for c in get_coupon_calendar(bond.secid or bond.isin):
                        if c["date"] == tomorrow.strftime("%Y-%m-%d") and c["value"]:
                            due.append((
                                bond.name or bond.isin,
                                bond.isin,
                                round(float(c["value"]) * bond.amount, 2),
                            ))
                if not due:
                    continue

                # Telegram
                if has_tg and user.telegram_chat_id and user.telegram_notifications:
                    lines = "\n".join(f"• {n} ({i}): <b>{v} ₽</b>" for n, i, v in due)
                    text = (
                        f"📅 <b>Купонные выплаты завтра ({tomorrow}):</b>\n\n"
                        + lines
                        + "\n\n<i>InvestTrack — ваш трекер облигаций</i>"
                    )
                    tg_send(user.telegram_chat_id, text)

        except Exception as exc:
            logger.error("Coupon reminder job failed: %s", exc)


# Start scheduler only outside tests and in the real server process
# (WERKZEUG_RUN_MAIN == 'true' in the reload child, unset in the parent watchdog)
_in_test = os.environ.get("FLASK_TESTING") == "1"
_is_reload_parent = app.debug and os.environ.get("WERKZEUG_RUN_MAIN") is None

if not _in_test and not _is_reload_parent:
    try:
        from apscheduler.schedulers.background import BackgroundScheduler

        _scheduler = BackgroundScheduler(daemon=True)
        _scheduler.add_job(
            _update_bond_prices,
            "interval",
            minutes=15,
            id="price_update",
            max_instances=1,
            misfire_grace_time=60,
        )
        _scheduler.add_job(
            _send_coupon_reminders,
            "cron",
            hour=9,
            minute=0,
            id="coupon_reminders",
            max_instances=1,
            misfire_grace_time=600,
        )
        _scheduler.start()
        atexit.register(lambda: _scheduler.shutdown(wait=False))
        logger.info("APScheduler started: price_update every 15 min")
    except Exception as _sched_err:
        logger.warning("Could not start APScheduler: %s", _sched_err)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug_mode, port=5000)

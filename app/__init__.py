import atexit
import logging
import os
import secrets
import subprocess
import tempfile
from datetime import datetime, timezone

try:
    import fcntl as _fcntl

    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False  # Windows

from flask import Flask, g, request, jsonify, render_template, session
from flask_cors import CORS
from flask_login import logout_user, current_user
from flask_wtf import CSRFProtect
from flask_wtf.csrf import generate_csrf
from werkzeug.exceptions import RequestEntityTooLarge

from app.config import get_config
from app.extensions import db, login_manager, migrate, cache, limiter, mail

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

csrf = CSRFProtect()


def create_app(config_class=None) -> Flask:
    """Создаёт и настраивает экземпляр Flask-приложения (Application Factory)."""
    app = Flask(__name__)

    if config_class is None:
        app.config.from_object(get_config())
    else:
        app.config.from_object(config_class)

    # ── Sentry (опционально) ──────────────────────────────────────────────────
    if os.environ.get("SENTRY_DSN") and not app.testing:
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
                traces_sample_rate=float(os.environ.get("SENTRY_TRACES_RATE", "0.1")),
                send_default_pii=False,
                environment=os.environ.get("FLASK_ENV", "development"),
            )
        except ImportError:
            pass

    # ── Инициализация расширений ──────────────────────────────────────────────
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "main.index_page"
    login_manager.login_message = "Пожалуйста, войдите для доступа к этой странице."
    migrate.init_app(app, db)

    # Кэш: NullCache в тестах, иначе Redis (если REDIS_URL задан) → FileSystemCache
    if app.config.get("TESTING") or os.environ.get("FLASK_TESTING") == "1":
        _cache_config = {"CACHE_TYPE": "NullCache"}
    elif app.config.get("REDIS_URL"):
        _cache_config = {
            "CACHE_TYPE": "RedisCache",
            "CACHE_REDIS_URL": app.config["REDIS_URL"],
        }
    else:
        _cache_config = {
            "CACHE_TYPE": "FileSystemCache",
            "CACHE_DIR": os.path.join(app.root_path, ".cache"),
            "CACHE_THRESHOLD": 1000,
            "CACHE_DEFAULT_TIMEOUT": 300,
        }
    cache.init_app(app, config=_cache_config)
    mail.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    CORS(app, supports_credentials=True, origins=app.config["CORS_ORIGINS"])

    # ── Static asset versioning (cache-busting) ───────────────────────────────
    try:
        _git_hash = (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=os.path.dirname(__file__),
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except Exception:
        _git_hash = "1"
    app.jinja_env.globals["static_ver"] = _git_hash

    # ── Blueprints ────────────────────────────────────────────────────────────
    from app.blueprints.main import main_bp
    from app.blueprints.auth import auth_bp
    from app.blueprints.admin import admin_bp
    from app.blueprints.profile import profile_bp
    from app.blueprints.portfolio import portfolio_bp
    from app.blueprints.telegram_bot import telegram_bp
    from app.blueprints.analytics import analytics_bp
    from app.blueprints.imports import imports_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(portfolio_bp)
    app.register_blueprint(telegram_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(imports_bp)

    csrf.exempt(telegram_bp)

    # ── CSP nonce: генерируется на каждый запрос ─────────────────────────────
    @app.before_request
    def generate_csp_nonce():
        g.csp_nonce = secrets.token_urlsafe(16)

    # ── Idle timeout: сброс сессии после 30 мин бездействия ───────────────────
    @app.before_request
    def enforce_idle_timeout():
        if not current_user.is_authenticated:
            return

        idle_timeout = app.config.get("IDLE_TIMEOUT_SECONDS", 1800)
        now = datetime.now(timezone.utc).timestamp()
        last_active = session.get("_last_active", now)

        if now - last_active > idle_timeout:
            logout_user()
            session.clear()
            if request.path.startswith("/api/"):
                return jsonify(
                    {
                        "status": "error",
                        "code": 401,
                        "message": "Сессия истекла из-за неактивности. Войдите снова.",
                    }
                ), 401
            return

        session["_last_active"] = now

        # ── Security headers (после каждого ответа) ──────────────────────────────

    @app.after_request
    def set_security_headers(response):
        # Игнорируем статику, чтобы не ломать кэш и не плодить пустые сессии
        if request.path.startswith("/static/") or request.path == "/favicon.ico":
            return response

        try:
            token = generate_csrf()
            _lifetime = app.config.get("PERMANENT_SESSION_LIFETIME")
            _max_age = int(_lifetime.total_seconds()) if _lifetime else 7 * 24 * 3600
            response.set_cookie(
                "XSRF-TOKEN",
                token,
                httponly=False,
                samesite="Lax",
                max_age=_max_age,
                secure=app.config.get("SESSION_COOKIE_SECURE", False),
            )
        except Exception:
            pass

        response.headers.remove("Server")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), camera=(), microphone=(), payment=()",
        )

        # CSP: 'unsafe-inline' needed for inline onclick handlers and style attributes
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "img-src 'self' data: ui-avatars.com fonts.gstatic.com; "
            "font-src 'self' fonts.gstatic.com fonts.googleapis.com; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "form-action 'self'"
        )

        if not app.debug and not app.testing:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )

        return response

    # ── User loader ───────────────────────────────────────────────────────────
    @login_manager.user_loader
    def load_user(user_id):
        from app.models import User

        return db.session.get(User, int(user_id))

    # ── Error handlers ────────────────────────────────────────────────────────
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
                error.description
                if hasattr(error, "description")
                else "Внутренняя ошибка сервера"
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

    # ── Prometheus Metrics Endpoint ───────────────────────────────────────────
    @app.route("/metrics")
    def prometheus_metrics():
        """Экспорт системных и бизнес-метрик приложения в формате Prometheus."""
        # Базовая защита: требуем токен (например, /metrics?token=MySecretToken123)
        expected_token = app.config.get("METRICS_TOKEN")
        if expected_token and request.args.get("token") != expected_token:
            return "Unauthorized", 401

        try:
            from app.models import User, BondPortfolio, Transaction

            user_count = db.session.query(User).count()
            portfolio_count = db.session.query(BondPortfolio).count()
            tx_count = db.session.query(Transaction).count()
            status = 1
        except Exception:
            user_count = portfolio_count = tx_count = 0
            status = 0

        lines = [
            "# HELP investtrack_active_positions_total Total active bond positions in database",
            "# TYPE investtrack_active_positions_total gauge",
            f"investtrack_active_positions_total {portfolio_count}",
            "# HELP investtrack_users_total Total registered users in database",
            "# TYPE investtrack_users_total gauge",
            f"investtrack_users_total {user_count}",
            "# HELP investtrack_transactions_total Total transactions in database",
            "# TYPE investtrack_transactions_total gauge",
            f"investtrack_transactions_total {tx_count}",
            "# HELP investtrack_system_status Database connection health status (1 = healthy, 0 = unhealthy)",
            "# TYPE investtrack_system_status gauge",
            f"investtrack_system_status {status}",
        ]
        return (
            "\n".join(lines) + "\n",
            200,
            {"Content-Type": "text/plain; charset=utf-8"},
        )

    # ── Инициализация планировщика задач ──────────────────────────────────────
    _in_test = app.config.get("TESTING") or os.environ.get("FLASK_TESTING") == "1"
    _is_reload_parent = app.debug and os.environ.get("WERKZEUG_RUN_MAIN") is None

    if not _in_test and not _is_reload_parent and _try_acquire_scheduler_lock():
        try:
            from apscheduler.schedulers.background import BackgroundScheduler

            scheduler = BackgroundScheduler(daemon=True)
            scheduler.add_job(
                _update_bond_prices,
                "interval",
                minutes=15,
                id="price_update",
                max_instances=1,
                misfire_grace_time=60,
                args=[app],
            )
            scheduler.add_job(
                _send_coupon_reminders,
                "cron",
                hour=9,
                minute=0,
                id="coupon_reminders",
                max_instances=1,
                misfire_grace_time=600,
                args=[app],
            )
            scheduler.start()
            atexit.register(lambda: scheduler.shutdown(wait=False))
            logger.info(
                "APScheduler started (pid=%d): price_update every 15 min", os.getpid()
            )
        except Exception as _sched_err:
            logger.warning("Could not start APScheduler: %s", _sched_err)

    return app


# ── APScheduler: background jobs ─────────────────────────────────────────────
def _update_bond_prices(app) -> None:
    """Обновляет last_price всех активных облигаций через bulk UPDATE.
    Параллелизирует запросы к MOEX через ThreadPoolExecutor для максимальной скорости.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    with app.app_context():
        try:
            from app.models import BondPortfolio
            from app.moex import get_moex_bond
            from app.constants import MOEX_BOND_TTL

            active = BondPortfolio.query.filter_by(is_sold=False).all()
            if not active:
                return

            # 1) Собираем уникальные ISINы и запрашиваем MOEX параллельно
            isin_targets = list({bond.isin for bond in active})
            seen: dict[str, dict | None] = {}

            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {
                    executor.submit(get_moex_bond, isin): isin for isin in isin_targets
                }
                for future in as_completed(futures):
                    isin = futures[future]
                    try:
                        res = future.result()
                        seen[isin] = res
                        if res:
                            cache.set(f"moex_bond:{isin}", res, timeout=MOEX_BOND_TTL)
                    except Exception as e:
                        logger.warning(
                            "Error fetching %s in background price update: %s", isin, e
                        )

            # 2) Bulk UPDATE — один SQL вместо N отдельных UPDATE
            mappings = [
                {"id": bond.id, "last_price": seen[bond.isin]["price"]}
                for bond in active
                if seen.get(bond.isin)
            ]
            if mappings:
                db.session.bulk_update_mappings(BondPortfolio, mappings)
                db.session.commit()

            # 3) Проверка ценовых алертов
            try:
                _check_price_alerts(seen)
            except Exception as e:
                logger.error("Price alerts check failed: %s", e)

            logger.info(
                "Price update: %d ISINs, %d bonds updated",
                len([v for v in seen.values() if v]),
                len(mappings),
            )
        except Exception as exc:
            logger.error("Price update job failed: %s", exc)


def _send_coupon_reminders(app) -> None:
    """Рассылает напоминания о купонах завтра — через email и/или Telegram."""
    with app.app_context():
        has_tg = bool(app.config.get("TELEGRAM_BOT_TOKEN"))
        if not has_tg:
            return
        try:
            from app.models import User, BondPortfolio
            from app.moex import get_coupon_calendar
            from datetime import date, timedelta
            from app.services.telegram_service import send_message as tg_send

            tomorrow = date.today() + timedelta(days=1)

            # Собираем пользователей с Telegram-каналом уведомлений
            users = User.query.filter(
                db.and_(
                    User.telegram_chat_id.isnot(None),
                    User.telegram_notifications.is_(True),
                )
            ).all()

            for user in users:
                bonds = BondPortfolio.query.filter_by(
                    user_id=user.id, is_sold=False
                ).all()
                due = []
                for bond in bonds:
                    for c in get_coupon_calendar(bond.secid or bond.isin):
                        if c["date"] == tomorrow.strftime("%Y-%m-%d") and c["value"]:
                            due.append(
                                (
                                    bond.name or bond.isin,
                                    bond.isin,
                                    round(float(c["value"]) * bond.amount, 2),
                                )
                            )
                if not due:
                    continue

                if has_tg:
                    lines = "\n".join(f"• {n} ({i}): <b>{v} ₽</b>" for n, i, v in due)
                    text = (
                        f"📅 <b>Купонные выплаты завтра ({tomorrow}):</b>\n\n"
                        + lines
                        + "\n\n<i>InvestTrack — ваш трекер облигаций</i>"
                    )
                    tg_send(user.telegram_chat_id, text)

        except Exception as exc:
            logger.error("Coupon reminder job failed: %s", exc)


def _check_price_alerts(prices_map: dict) -> None:
    """Вспомогательный метод для проверки активных ценовых алертов."""
    from app.models import User
    from app.services.telegram_service import send_message as tg_send

    # Импортируем локально, так как модель PriceAlert может быть создана динамически
    try:
        from app.models import PriceAlert
    except ImportError:
        return

    alerts = PriceAlert.query.filter_by(is_triggered=False).all()
    if not alerts:
        return

    for alert in alerts:
        bond_data = prices_map.get(alert.isin)
        if not bond_data or bond_data.get("price") is None:
            continue

        current_price = float(bond_data["price"])
        target_price = float(alert.target_price)
        triggered = False

        if alert.condition == ">=" and current_price >= target_price:
            triggered = True
        elif alert.condition == "<=" and current_price <= target_price:
            triggered = True

        if triggered:
            alert.is_triggered = True
            db.session.commit()

            user = db.session.get(User, alert.user_id)
            if user and user.telegram_chat_id and user.telegram_notifications:
                msg = (
                    f"🔔 <b>Ценовой алерт сработал!</b>\n\n"
                    f"Бумага: <b>{alert.name or alert.isin}</b> ({alert.isin})\n"
                    f"Целевая цена: {target_price} ₽ ({alert.condition})\n"
                    f"Текущая цена: <b>{current_price} ₽</b>"
                )
                try:
                    tg_send(user.telegram_chat_id, msg)
                except Exception as e:
                    logger.warning(
                        "Failed to send alert notification to Telegram chat %s: %s",
                        user.telegram_chat_id,
                        e,
                    )


def _try_acquire_scheduler_lock() -> bool:
    """Возвращает True если этот процесс стал владельцем файлового замка.
    На Windows fcntl недоступен — возвращает True сразу (Gunicorn там не используется).
    """
    if not _HAS_FCNTL:
        return True
    try:
        lock_path = os.path.join(tempfile.gettempdir(), "investtrack_scheduler.lock")
        _fd = open(lock_path, "w")
        _fcntl.flock(_fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        atexit.register(lambda: _fd.close())
        return True
    except OSError:
        return False


# Экспортируем дефолтный инстанс для полной обратной совместимости с тестами и сервером.
app = create_app()

if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug_mode, port=5000)

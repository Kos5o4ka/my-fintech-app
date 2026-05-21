import atexit
import logging
import os

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from flask_wtf import CSRFProtect
from flask_wtf.csrf import generate_csrf
from werkzeug.exceptions import RequestEntityTooLarge

from config import Config
from extensions import db, login_manager, migrate, cache, limiter
from models import User

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(Config)

# ── Extensions ────────────────────────────────────────────────────────────────
db.init_app(app)
login_manager.init_app(app)
migrate.init_app(app, db)
cache.init_app(app, config={"CACHE_TYPE": "SimpleCache"})
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

app.register_blueprint(main_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(profile_bp)
app.register_blueprint(portfolio_bp)


# ── Security headers (after every response) ───────────────────────────────────
@app.after_request
def set_security_headers(response):
    try:
        token = generate_csrf()
        response.set_cookie("XSRF-TOKEN", token, httponly=False, samesite="Lax")
    except Exception:
        pass
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
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


# ── APScheduler: background price refresh (ARCH-3) ───────────────────────────
def _update_bond_prices() -> None:
    """Refresh last_price for all active bonds and pre-warm the MOEX cache."""
    with app.app_context():
        try:
            from models import BondPortfolio
            from moex import get_moex_bond

            active = BondPortfolio.query.filter_by(is_sold=False).all()
            seen: dict = {}
            updated = 0
            for bond in active:
                if bond.isin not in seen:
                    seen[bond.isin] = get_moex_bond(bond.isin)
                data = seen[bond.isin]
                if data:
                    bond.last_price = data.get("price", bond.last_price)
                    try:
                        cache.set(f"moex_bond:{bond.isin}", data, timeout=900)
                    except Exception:
                        pass
                    updated += 1
            db.session.commit()
            logger.info("Price update job: refreshed %d ISINs (%d bonds)", len(seen), updated)
        except Exception as exc:
            logger.error("Price update job failed: %s", exc)


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
        _scheduler.start()
        atexit.register(lambda: _scheduler.shutdown(wait=False))
        logger.info("APScheduler started: price_update every 15 min")
    except Exception as _sched_err:
        logger.warning("Could not start APScheduler: %s", _sched_err)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug_mode, port=5000)

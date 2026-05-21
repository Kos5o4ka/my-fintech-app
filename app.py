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


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug_mode, port=5000)

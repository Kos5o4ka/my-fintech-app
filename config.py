import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()


class Config:
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-insecure-please-set-SECRET_KEY-env-var'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///local_fintech.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    REDIS_URL = os.environ.get('REDIS_URL')
    CORS_ORIGINS = os.environ.get('CORS_ORIGINS', 'http://127.0.0.1:5000,http://localhost:5000').split(',')
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'avatars')
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = False
    # Сессии: постоянные (7 дней) + idle timeout (30 мин — проверяется в before_request)
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    IDLE_TIMEOUT_SECONDS = int(os.environ.get('IDLE_TIMEOUT_SECONDS', 1800))
    # Flask-Mail (optional — set MAIL_SERVER in .env to enable email notifications)
    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@investtrack.app')
    # Telegram Bot (optional — set TELEGRAM_BOT_TOKEN in .env to enable Telegram features)
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
    TELEGRAM_BOT_USERNAME = os.environ.get('TELEGRAM_BOT_USERNAME', 'InvestTrackBot')
    # Sentry (optional — set SENTRY_DSN to enable error tracking)
    SENTRY_DSN = os.environ.get('SENTRY_DSN')


class DevelopmentConfig(Config):
    DEBUG = True


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'test-secret-key'
    MAIL_SUPPRESS_SEND = True


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True

    # Connection pooling — только для PostgreSQL, SQLite не поддерживает
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_size": int(os.environ.get("DB_POOL_SIZE", 5)),
        "max_overflow": int(os.environ.get("DB_MAX_OVERFLOW", 10)),
        "pool_timeout": 30,
        "pool_recycle": 1800,  # переподключение каждые 30 мин (для NAT/firewall)
    }

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    @classmethod
    def validate(cls):
        key = os.environ.get('SECRET_KEY', '')
        if not key or key == 'change-me-before-production':
            raise RuntimeError(
                "SECRET_KEY environment variable must be set to a strong random value in production."
            )


# Map name → class; used by app.py and tests
_CONFIG_MAP = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
}


def get_config() -> type:
    env = os.environ.get('FLASK_ENV', 'development').lower()
    cfg = _CONFIG_MAP.get(env, DevelopmentConfig)
    if cfg is ProductionConfig:
        ProductionConfig.validate()
    return cfg

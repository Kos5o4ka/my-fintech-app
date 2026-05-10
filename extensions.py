from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_caching import Cache
from flask_migrate import Migrate  # Добавили это

db = SQLAlchemy()
login_manager = LoginManager()
cache = Cache()
migrate = Migrate()  # Инициализируем здесь
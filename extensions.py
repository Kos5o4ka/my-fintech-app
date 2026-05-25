from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_caching import Cache
from flask_migrate import Migrate
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_mail import Mail

db = SQLAlchemy()
login_manager = LoginManager()
cache = Cache()
migrate = Migrate()
mail = Mail()
limiter = Limiter(
    key_func=get_remote_address, default_limits=["500 per day", "100 per hour"]
)

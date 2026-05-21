import sys
import os
import secrets

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app
from extensions import db
from werkzeug.security import generate_password_hash
from models import User

with app.app_context():
    db.create_all()
    print("Tables created or already exist")

    admin = db.session.query(User).filter_by(username='admin').first()
    if not admin:
        admin_password = secrets.token_urlsafe(16)
        admin = User(
            username='admin',
            password_hash=generate_password_hash(admin_password),
            is_admin=True,
        )
        db.session.add(admin)
        db.session.commit()
        print("=" * 60)
        print(f"  Admin user created: username='admin'")
        print(f"  Password: {admin_password}")
        print("  SAVE THIS PASSWORD — it will not be shown again!")
        print("=" * 60)
    else:
        print("Admin user already exists: %s" % admin.username)

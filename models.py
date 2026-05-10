from datetime import datetime
from extensions import db
from flask_login import UserMixin

class Visit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    count = db.Column(db.Integer, default=1)

class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    avatar = db.Column(db.String(255), default='default_avatar.png')

class BondPortfolio(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    isin = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    buy_price = db.Column(db.Float, nullable=False)
    purchase_date = db.Column(db.Date, nullable=False)
    
    # --- НОВЫЕ ПОЛЯ ДЛЯ ПРОДАЖИ И ФОНОВЫХ ЗАДАЧ ---
    is_sold = db.Column(db.Boolean, default=False)
    sell_price = db.Column(db.Float, nullable=True)
    sell_date = db.Column(db.Date, nullable=True)
    realized_profit = db.Column(db.Float, default=0.0)
    
    # Поля для хранения цен из фонового обновления
    last_price = db.Column(db.Float, nullable=True) 
    last_updated = db.Column(db.DateTime, nullable=True)
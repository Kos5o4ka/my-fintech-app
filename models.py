from datetime import date, datetime
from extensions import db
from flask_login import UserMixin

class Visit(db.Model):
    __tablename__ = 'visit'
    id = db.Column(db.Integer, primary_key=True)
    count = db.Column(db.Integer, default=0)

class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    avatar = db.Column(db.String(255), nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    email = db.Column(db.String(254), nullable=True)
    email_notifications = db.Column(db.Boolean, default=False)
    # Stage 3 — Telegram-бот
    telegram_chat_id = db.Column(db.String(20), nullable=True, unique=True)
    telegram_notifications = db.Column(db.Boolean, default=False)
    telegram_username = db.Column(db.String(64), nullable=True)
    bonds = db.relationship('BondPortfolio', backref='user', lazy=True)

class BondPortfolio(db.Model):
    __tablename__ = 'bond_portfolio'
    __table_args__ = (
        db.Index('ix_bp_user_id', 'user_id'),
        db.Index('ix_bp_is_sold', 'is_sold'),
        db.Index('ix_bp_user_sold', 'user_id', 'is_sold'),
        db.Index('ix_bp_isin', 'isin'),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    isin = db.Column(db.String(12), nullable=False)
    secid = db.Column(db.String(50), nullable=True)
    name = db.Column(db.String(100), nullable=True)
    amount = db.Column(db.Integer, nullable=False)
    buy_price = db.Column(db.Numeric(10, 2), nullable=False)
    purchase_date = db.Column(db.Date, nullable=False, default=date.today)
    is_sold = db.Column(db.Boolean, default=False)
    last_price = db.Column(db.Numeric(10, 2), nullable=True)
    sell_price = db.Column(db.Numeric(10, 2), nullable=True)
    sell_date = db.Column(db.Date, nullable=True)
    broker_commission = db.Column(db.Numeric(10, 4), nullable=True)
    currency = db.Column(db.String(3), nullable=False, default='RUB')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # Stage 4 — заметки к позиции
    notes = db.Column(db.Text, nullable=True)


class Watchlist(db.Model):
    __tablename__ = 'watchlist'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'isin', name='uq_watchlist_user_isin'),
        db.Index('ix_wl_user_id', 'user_id'),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    isin = db.Column(db.String(12), nullable=False)
    secid = db.Column(db.String(50), nullable=True)
    name = db.Column(db.String(100), nullable=True)
    added_at = db.Column(db.Date, nullable=False, default=date.today)


class Transaction(db.Model):
    __tablename__ = 'transactions'
    __table_args__ = (
        db.Index('ix_tx_user_id', 'user_id'),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    isin = db.Column(db.String(12), nullable=False)
    name = db.Column(db.String(100), nullable=True)
    tx_type = db.Column(db.String(10), nullable=False)  # 'buy' | 'sell' | 'coupon'
    amount = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    commission = db.Column(db.Numeric(10, 4), nullable=True)
    currency = db.Column(db.String(3), nullable=False, default='RUB')
    tx_date = db.Column(db.Date, nullable=False, default=date.today)


class AuditLog(db.Model):
    """Журнал действий пользователей — вход, выход, смена пароля и т.д."""
    __tablename__ = 'audit_log'
    __table_args__ = (
        db.Index('ix_audit_user_id', 'user_id'),
        db.Index('ix_audit_created_at', 'created_at'),
    )
    id = db.Column(db.Integer, primary_key=True)
    # nullable=True — чтобы логировать и неудачные попытки входа (без user_id)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    action = db.Column(db.String(50), nullable=False)   # login_ok | login_fail | logout | change_password | tg_link | tg_unlink
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    details = db.Column(db.Text, nullable=True)         # JSON или текстовое описание
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
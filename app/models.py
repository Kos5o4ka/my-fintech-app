from datetime import date, datetime
from app.extensions import db
from flask_login import UserMixin
from sqlalchemy import JSON


class Visit(db.Model):
    __tablename__ = "visit"
    id = db.Column(db.Integer, primary_key=True)
    count = db.Column(db.Integer, default=0)


class User(db.Model, UserMixin):
    __tablename__ = "users"
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
    two_fa_enabled = db.Column(db.Boolean, default=True)
    # Stage 12 — Settings
    theme = db.Column(db.String(10), nullable=False, default="system")
    notif_time = db.Column(db.String(5), nullable=False, default="09:00")
    notif_timezone = db.Column(db.String(64), nullable=False, default="Europe/Moscow")
    oferta_advance_days = db.Column(db.Integer, nullable=False, default=14)
    bonds = db.relationship(
        "BondPortfolio", backref="user", lazy=True, cascade="all, delete-orphan"
    )
    watchlists = db.relationship(
        "Watchlist", backref="user", lazy=True, cascade="all, delete-orphan"
    )
    transactions = db.relationship(
        "Transaction", backref="user", lazy=True, cascade="all, delete-orphan"
    )
    price_alerts = db.relationship(
        "PriceAlert", backref="user", lazy=True, cascade="all, delete-orphan"
    )
    audit_logs = db.relationship(
        "AuditLog", backref="user", lazy=True, cascade="all, delete-orphan"
    )


class BondPortfolio(db.Model):
    __tablename__ = "bond_portfolio"
    __table_args__ = (
        db.Index("ix_bp_user_id", "user_id"),
        db.Index("ix_bp_is_sold", "is_sold"),
        db.Index("ix_bp_user_sold", "user_id", "is_sold"),
        db.Index("ix_bp_isin", "isin"),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
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
    currency = db.Column(db.String(3), nullable=False, default="RUB")
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    # Stage 4 — заметки к позиции
    notes = db.Column(db.Text, nullable=True)
    buy_deal_no = db.Column(db.String(100), nullable=True)
    sell_deal_no = db.Column(db.String(100), nullable=True)


class Watchlist(db.Model):
    __tablename__ = "watchlist"
    __table_args__ = (
        db.UniqueConstraint("user_id", "isin", name="uq_watchlist_user_isin"),
        db.Index("ix_wl_user_id", "user_id"),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    isin = db.Column(db.String(12), nullable=False)
    secid = db.Column(db.String(50), nullable=True)
    name = db.Column(db.String(100), nullable=True)
    added_at = db.Column(db.Date, nullable=False, default=date.today)


class Transaction(db.Model):
    __tablename__ = "transactions"
    __table_args__ = (db.Index("ix_tx_user_id", "user_id"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    isin = db.Column(db.String(12), nullable=False)
    name = db.Column(db.String(100), nullable=True)
    tx_type = db.Column(db.String(10), nullable=False)  # 'buy' | 'sell' | 'coupon'
    amount = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    commission = db.Column(db.Numeric(10, 4), nullable=True)
    currency = db.Column(db.String(3), nullable=False, default="RUB")
    tx_date = db.Column(db.Date, nullable=False, default=date.today)
    # FIFO / ст. 214.1 НК РФ
    nkd = db.Column(db.Numeric(10, 4), nullable=True)
    portfolio_id = db.Column(
        db.Integer, db.ForeignKey("bond_portfolio.id"), nullable=True
    )
    deal_no = db.Column(db.String(100), nullable=True, index=True)


class AuditLog(db.Model):
    """Журнал действий пользователей — аккаунт и портфель."""

    __tablename__ = "audit_log"
    __table_args__ = (
        db.Index("ix_audit_user_id", "user_id"),
        db.Index("ix_audit_created_at", "created_at"),
        db.Index("ix_audit_user_category", "user_id", "category"),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    action = db.Column(db.String(50), nullable=False)
    category = db.Column(db.String(20), nullable=False, default="account")
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    details = db.Column(JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SiteNotification(db.Model):
    """Уведомления на сайте (от админа к пользователям)."""

    __tablename__ = "site_notifications"
    __table_args__ = (
        db.Index("ix_site_notif_user_unread", "user_id", "is_read"),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=True)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class PriceAlert(db.Model):
    """Ценовые алерты пользователя для отслеживания стоимости облигаций."""

    __tablename__ = "price_alerts"
    __table_args__ = (
        db.Index("ix_alerts_user_id", "user_id"),
        db.Index("ix_alerts_isin", "isin"),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    isin = db.Column(db.String(12), nullable=False)
    name = db.Column(db.String(100), nullable=True)
    target_price = db.Column(db.Numeric(10, 2), nullable=False)
    condition = db.Column(db.String(5), nullable=False)  # '>=' или '<='
    is_triggered = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

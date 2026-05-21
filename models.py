from datetime import datetime
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
    bonds = db.relationship('BondPortfolio', backref='user', lazy=True)

class BondPortfolio(db.Model):
    __tablename__ = 'bond_portfolio'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    isin = db.Column(db.String(12), nullable=False)
    name = db.Column(db.String(100), nullable=True)
    amount = db.Column(db.Integer, nullable=False)
    buy_price = db.Column(db.Numeric(10, 2), nullable=False)
    purchase_date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    is_sold = db.Column(db.Boolean, default=False)
    last_price = db.Column(db.Numeric(10, 2), nullable=True)
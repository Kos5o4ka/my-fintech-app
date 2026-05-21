import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'prod-fintech-key-2026-xyz'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///local_fintech.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
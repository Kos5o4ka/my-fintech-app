"""Однократный скрипт миграции: заполняет таблицу transactions из bond_portfolio.

Запускать один раз после применения stage9_fifo_and_audit_json:
    flask db upgrade
    python scripts/migrate_to_transactions.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import app
from extensions import db
from models import BondPortfolio, Transaction


def migrate():
    with app.app_context():
        migrated = 0
        skipped = 0
        for bond in BondPortfolio.query.all():
            if Transaction.query.filter_by(portfolio_id=bond.id).first():
                skipped += 1
                continue
            db.session.add(
                Transaction(
                    user_id=bond.user_id,
                    isin=bond.isin,
                    name=bond.name,
                    tx_type="buy",
                    amount=bond.amount,
                    price=bond.buy_price,
                    commission=bond.broker_commission,
                    currency=bond.currency or "RUB",
                    tx_date=bond.purchase_date,
                    portfolio_id=bond.id,
                )
            )
            if bond.is_sold and bond.sell_price:
                db.session.add(
                    Transaction(
                        user_id=bond.user_id,
                        isin=bond.isin,
                        name=bond.name,
                        tx_type="sell",
                        amount=bond.amount,
                        price=bond.sell_price,
                        commission=bond.broker_commission,
                        currency=bond.currency or "RUB",
                        tx_date=bond.sell_date,
                        portfolio_id=bond.id,
                    )
                )
            migrated += 1

        db.session.commit()
        print(f"Done: {migrated} bonds migrated, {skipped} already had transactions.")


if __name__ == "__main__":
    migrate()

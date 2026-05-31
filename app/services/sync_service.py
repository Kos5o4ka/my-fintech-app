import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from flask import current_app
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import BrokerAccount, BrokerOperation, BrokerPosition, User
from app.services.tinvest_client import (
    TInvestClient,
    get_encryption_key,
    money_value_to_float,
    quotation_to_float,
    timestamp_to_datetime
)
import urllib.parse
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import os

logger = logging.getLogger(__name__)

def decrypt_token(encrypted_token_hex: str) -> str:
    key = get_encryption_key()
    try:
        data = bytes.fromhex(encrypted_token_hex)
        iv = data[:16]
        ciphertext = data[16:]
        cipher = Cipher(algorithms.AES(key), modes.CFB(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        decrypted = decryptor.update(ciphertext) + decryptor.finalize()
        return decrypted.decode('utf-8')
    except Exception as e:
        logger.error(f"Token decryption failed: {e}")
        return ""


def sync_user_tinvest(user_id: int):
    """
    Synchronize all Tinkoff accounts, operations and portfolio positions for a user.
    """
    user = db.session.get(User, user_id)
    if not user or not user.tinkoff_token:
        logger.info(f"User {user_id} has no tinkoff token. Skipping sync.")
        return

    token = decrypt_token(user.tinkoff_token)
    if not token:
        logger.error(f"Failed to decrypt token for user {user_id}")
        return

    client = TInvestClient(token)

    try:
        # 1. Sync accounts
        api_accounts = client.get_accounts()
        for api_acc in api_accounts:
            acc_id = api_acc.get("id")
            if not acc_id:
                continue
            
            account = db.session.get(BrokerAccount, acc_id)
            if not account:
                account = BrokerAccount(
                    id=acc_id,
                    user_id=user.id,
                    name=api_acc.get("name", "Tinkoff Account"),
                    type=api_acc.get("type", "UNKNOWN"),
                    status=api_acc.get("status", "UNKNOWN")
                )
                db.session.add(account)
            else:
                account.name = api_acc.get("name", account.name)
                account.status = api_acc.get("status", account.status)

        db.session.commit()

        # 2. For each open account, sync operations and portfolio
        for account in user.broker_accounts:
            if account.status != "ACCOUNT_STATUS_OPEN":
                continue

            _sync_operations(client, account)
            _sync_portfolio(client, account)

            account.last_synced_at = datetime.now(timezone.utc)
            db.session.commit()

    except Exception as e:
        logger.error(f"Failed to sync tinkoff data for user {user_id}: {e}")
        db.session.rollback()


def _sync_operations(client: TInvestClient, account: BrokerAccount):
    # Fetch from beginning of time or last sync
    # Tinkoff API allows max 1 year per request, but we simplify for MVP
    # and fetch last 3 years in chunks if needed. For now, fetch last year.
    now = datetime.now(timezone.utc)
    one_year_ago = now - timedelta(days=365)
    
    api_ops = client.get_operations(account.id, one_year_ago, now)
    
    # We use a set of existing IDs to avoid IntegrityError or UPSERT
    existing_ops = {op.id for op in db.session.query(BrokerOperation.id).filter_by(account_id=account.id).all()}

    for op in api_ops:
        op_id = op.get("id")
        if not op_id or op_id in existing_ops:
            continue

        payment = money_value_to_float(op.get("payment"))
        price = money_value_to_float(op.get("price"))
        commission = money_value_to_float(op.get("commission"))
        nkd = money_value_to_float(op.get("yield")) # Sometimes nkd is in yield or specific field
        
        # Determine actual quantity
        qty = float(op.get("quantity") or 0)
        
        op_date = timestamp_to_datetime(op.get("date")) or now

        # Create new operation
        new_op = BrokerOperation(
            id=op_id,
            account_id=account.id,
            figi=op.get("figi", ""),
            type=op.get("operationType", "UNKNOWN"),
            date=op_date,
            quantity=qty,
            price=price,
            payment=payment,
            commission=commission,
            nkd=nkd,
            currency=op.get("currency", "RUB")
        )
        db.session.add(new_op)
    
    db.session.commit()


def _sync_portfolio(client: TInvestClient, account: BrokerAccount):
    portfolio = client.get_portfolio(account.id)
    if not portfolio:
        return

    # Delete old positions to do a fresh snapshot
    db.session.query(BrokerPosition).filter_by(account_id=account.id).delete()

    positions = portfolio.get("positions", [])
    for pos in positions:
        qty = quotation_to_float(pos.get("quantity"))
        avg_price = money_value_to_float(pos.get("averagePositionPriceFifo") or pos.get("averagePositionPrice"))
        cur_price = money_value_to_float(pos.get("currentPrice"))
        expected_yield = money_value_to_float(pos.get("expectedYield"))
        
        new_pos = BrokerPosition(
            account_id=account.id,
            figi=pos.get("figi", ""),
            instrument_type=pos.get("instrumentType", ""),
            quantity=qty,
            average_price=avg_price,
            current_price=cur_price,
            expected_yield=expected_yield,
            currency=pos.get("currentPrice", {}).get("currency", "RUB")
        )
        db.session.add(new_pos)
    
    db.session.commit()

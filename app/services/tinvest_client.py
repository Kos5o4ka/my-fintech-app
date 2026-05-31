import asyncio
import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://invest-public-api.tbank.ru/rest"


def get_encryption_key() -> bytes:
    key_hex = os.environ.get("ENCRYPTION_KEY", "")
    if len(key_hex) != 64:
        raise ValueError("ENCRYPTION_KEY must be a 64-character hex string.")
    return bytes.fromhex(key_hex)


def money_value_to_float(mv: dict) -> float:
    if not mv:
        return 0.0
    units = int(mv.get("units") or 0)
    nano = int(mv.get("nano") or 0)
    return float(units) + float(nano) / 1_000_000_000


def quotation_to_float(q: dict) -> float:
    if not q:
        return 0.0
    units = int(q.get("units") or 0)
    nano = int(q.get("nano") or 0)
    return float(units) + float(nano) / 1_000_000_000


def timestamp_to_datetime(ts: dict) -> Optional[datetime]:
    if not ts or not ts.get("seconds"):
        return None
    return datetime.fromtimestamp(int(ts["seconds"]))


class TInvestClient:
    def __init__(self, token: str):
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _request(self, method_path: str, payload: dict) -> dict:
        url = f"{BASE_URL}/{method_path}"
        max_retries = 3
        for attempt in range(max_retries):
            resp = requests.post(url, headers=self.headers, json=payload, timeout=30)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 429:
                # Rate limit exceeded
                wait_sec = 2 ** attempt
                logger.warning(f"Rate limit exceeded for {method_path}. Waiting {wait_sec}s.")
                time.sleep(wait_sec)
                continue
            elif resp.status_code == 401:
                raise ValueError("Unauthorized. Token may be invalid or expired.")
            else:
                resp_text = resp.text
                logger.error(f"T-Invest API error {resp.status_code} on {method_path}: {resp_text}")
                raise RuntimeError(f"API Error {resp.status_code}: {resp_text}")
        raise RuntimeError(f"Max retries exceeded for {method_path}")

    def get_accounts(self) -> List[Dict]:
        data = self._request("tinkoff.public.invest.api.contract.v1.UsersService/GetAccounts", {})
        return data.get("accounts", [])

    def get_portfolio(self, account_id: str) -> Dict:
        return self._request(
            "tinkoff.public.invest.api.contract.v1.OperationsService/GetPortfolio",
            {"accountId": account_id, "currency": "RUB"}
        )

    def get_operations(self, account_id: str, from_date: datetime, to_date: datetime) -> List[Dict]:
        # Returns executed operations
        payload = {
            "accountId": account_id,
            "from": {"seconds": str(int(from_date.timestamp())), "nanos": 0},
            "to": {"seconds": str(int(to_date.timestamp())), "nanos": 0},
            "state": "OPERATION_STATE_EXECUTED",
        }
        data = self._request(
            "tinkoff.public.invest.api.contract.v1.OperationsService/GetOperations", payload
        )
        return data.get("operations", [])

    def get_instrument_by_figi(self, figi: str) -> Optional[Dict]:
        try:
            data = self._request(
                "tinkoff.public.invest.api.contract.v1.InstrumentsService/GetInstrumentBy",
                {"idType": "INSTRUMENT_ID_TYPE_FIGI", "id": figi}
            )
            return data.get("instrument")
        except Exception as e:
            logger.warning(f"Failed to fetch instrument {figi}: {e}")
            return None

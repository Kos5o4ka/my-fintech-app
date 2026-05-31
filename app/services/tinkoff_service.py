"""T-Invest (Т-Банк) REST API integration.

Архитектура:
    Blueprint → Schema → этот сервис → внешний REST API T-Invest
                                    ↘ SQLAlchemy (BondPortfolio / Transaction)

Документация публичных контрактов: invest-public-api.tbank.ru.
Все денежные значения возвращаются как MoneyValue/Quotation → конвертируем
в Decimal через хелперы. Токены шифруются Fernet'ом с ключом, производным
от SECRET_KEY (PBKDF2-HMAC-SHA256).
"""

from __future__ import annotations

import base64
import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Iterable, Optional

import requests
import urllib3
from cryptography.fernet import Fernet, InvalidToken

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from flask import current_app

from app.extensions import db
from app.models import BondPortfolio, Transaction, User

logger = logging.getLogger(__name__)

# ── Константы API ────────────────────────────────────────────────────────────

PROD_BASE_URL = "https://invest-public-api.tbank.ru/rest"
SANDBOX_BASE_URL = "https://sandbox-invest-public-api.tbank.ru/rest"

_SVC_USERS = "tinkoff.public.invest.api.contract.v1.UsersService"
_SVC_OPS = "tinkoff.public.invest.api.contract.v1.OperationsService"
_SVC_INSTR = "tinkoff.public.invest.api.contract.v1.InstrumentsService"
_SVC_MD = "tinkoff.public.invest.api.contract.v1.MarketDataService"

REQUEST_TIMEOUT = 15  # секунд на один HTTP-запрос
INSTRUMENT_BATCH = 5  # параллельность не используем — батч=пачка с паузой
INSTRUMENT_BATCH_PAUSE = 0.2  # 200 мс между батчами для соблюдения 200 RPM


# ── Шифрование токена ────────────────────────────────────────────────────────


def _derive_fernet_key(secret: str) -> bytes:
    """Производим 32-байтный ключ из SECRET_KEY через PBKDF2 и кодируем в urlsafe-base64."""
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        secret.encode("utf-8"),
        b"investtrack.tinkoff.v1",
        iterations=200_000,
        dklen=32,
    )
    return base64.urlsafe_b64encode(digest)


def _fernet() -> Fernet:
    secret = current_app.config.get("SECRET_KEY") or ""
    if len(secret) < 12:
        raise RuntimeError("SECRET_KEY слишком короткий для безопасного шифрования токена.")
    return Fernet(_derive_fernet_key(secret))


def encrypt_token(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_token(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise TInvestError("Не удалось расшифровать сохранённый токен T-Invest.") from exc


# ── Исключения ───────────────────────────────────────────────────────────────


class TInvestError(Exception):
    """Базовое исключение интеграции T-Invest."""


class TInvestAuthError(TInvestError):
    """Токен недействителен или истёк (40003)."""


class TInvestRateLimitError(TInvestError):
    """Превышен лимит запросов (50002)."""


# ── Конвертеры протоколных типов ─────────────────────────────────────────────


def money_to_decimal(mv: Optional[dict]) -> Decimal:
    """MoneyValue/Quotation → Decimal. {units: '114', nano: 250000000} → 114.25"""
    if not mv:
        return Decimal("0")
    units = Decimal(str(mv.get("units", "0") or "0"))
    nano = Decimal(str(mv.get("nano", 0) or 0)) / Decimal("1000000000")
    return units + nano


def quotation_to_decimal(q: Optional[dict]) -> Decimal:
    return money_to_decimal(q)


def timestamp_to_datetime(ts: Optional[dict]) -> Optional[datetime]:
    if not ts:
        return None
    seconds = int(ts.get("seconds", 0) or 0)
    if not seconds:
        return None
    return datetime.utcfromtimestamp(seconds)


def datetime_to_timestamp(dt: datetime) -> dict:
    return {"seconds": str(int(dt.timestamp())), "nanos": 0}


# ── HTTP-клиент ──────────────────────────────────────────────────────────────


@dataclass
class TInvestClient:
    """Тонкая обёртка над REST T-Invest. Один экземпляр = один токен."""

    token: str
    sandbox: bool = False
    session: Optional[requests.Session] = None

    def __post_init__(self) -> None:
        self.session = self.session or requests.Session()
        self.session.verify = False
        self.base_url = SANDBOX_BASE_URL if self.sandbox else PROD_BASE_URL

    # — Низкоуровневый POST с обработкой ошибок и единственным retry на 50002 —
    def _post(self, method: str, body: dict, _retry: bool = True) -> dict:
        url = f"{self.base_url}/{method}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            resp = self.session.post(url, json=body, headers=headers, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            raise TInvestError(f"Сетевая ошибка обращения к T-Invest: {exc}") from exc

        if resp.status_code == 401 or resp.status_code == 403:
            raise TInvestAuthError("Токен T-Invest устарел или недействителен.")
        if resp.status_code == 429:
            if _retry:
                time.sleep(2)
                return self._post(method, body, _retry=False)
            raise TInvestRateLimitError("Превышен лимит запросов T-Invest.")
        if not resp.ok:
            try:
                payload = resp.json()
                msg = payload.get("message") or payload.get("description") or resp.text
                code = str(payload.get("code", ""))
            except ValueError:
                msg, code = resp.text, ""
            if code == "40003":
                raise TInvestAuthError(msg or "Токен недействителен.")
            if code == "50002":
                raise TInvestRateLimitError(msg or "Rate limit.")
            raise TInvestError(f"T-Invest API {resp.status_code}: {msg}")
        try:
            return resp.json()
        except ValueError as exc:
            raise TInvestError("T-Invest вернул не-JSON ответ.") from exc

    # — Высокоуровневые методы —
    def get_accounts(self) -> list[dict]:
        data = self._post(f"{_SVC_USERS}/GetAccounts", {})
        return data.get("accounts", []) or []

    def get_portfolio(self, account_id: str, currency: str = "RUB") -> dict:
        return self._post(
            f"{_SVC_OPS}/GetPortfolio",
            {"accountId": account_id, "currency": currency},
        )

    def get_instrument_by_figi(self, figi: str) -> Optional[dict]:
        try:
            data = self._post(
                f"{_SVC_INSTR}/GetInstrumentBy",
                {"idType": "INSTRUMENT_ID_TYPE_FIGI", "id": figi},
            )
            return data.get("instrument")
        except TInvestError as exc:
            logger.warning("get_instrument_by_figi(%s) failed: %s", figi, exc)
            return None

    def batch_get_instruments(self, figis: Iterable[str]) -> dict[str, dict]:
        """Соблюдаем лимит 200 RPM: батчи по 5 + пауза 200 мс."""
        unique = list({f for f in figis if f})
        result: dict[str, dict] = {}
        for i in range(0, len(unique), INSTRUMENT_BATCH):
            batch = unique[i : i + INSTRUMENT_BATCH]
            for figi in batch:
                instr = self.get_instrument_by_figi(figi)
                if instr:
                    result[figi] = instr
            if i + INSTRUMENT_BATCH < len(unique):
                time.sleep(INSTRUMENT_BATCH_PAUSE)
        return result

    def get_last_prices(self, figis: list[str]) -> list[dict]:
        data = self._post(f"{_SVC_MD}/GetLastPrices", {"figi": figis})
        return data.get("lastPrices", []) or []

    def get_operations(
        self,
        account_id: str,
        date_from: datetime,
        date_to: datetime,
        figi: str = "",
    ) -> list[dict]:
        data = self._post(
            f"{_SVC_OPS}/GetOperations",
            {
                "accountId": account_id,
                "from": datetime_to_timestamp(date_from),
                "to": datetime_to_timestamp(date_to),
                "state": "OPERATION_STATE_EXECUTED",
                "figi": figi,
            },
        )
        return data.get("operations", []) or []


# ── Бизнес-логика: верификация токена и синхронизация ────────────────────────


def verify_token(plain_token: str, sandbox: bool = False) -> list[dict]:
    """Проверяем токен дёшево — через GetAccounts. Возвращаем список счетов."""
    client = TInvestClient(token=plain_token, sandbox=sandbox)
    return client.get_accounts()


def _bond_buy_price_from_position(pos: dict) -> Decimal:
    """T-Invest отдаёт averagePositionPrice в валюте бумаги. Для рублёвой ОФЗ
    это руб./шт. при номинале 1000. В нашей доменной модели buy_price хранится
    в % от номинала (как в MOEX). Конвертация выполняется ниже."""
    avg = money_to_decimal(pos.get("averagePositionPrice"))
    return avg


@dataclass
class SyncSummary:
    accounts: int = 0
    positions_total: int = 0
    bonds_imported: int = 0
    bonds_updated: int = 0
    bonds_skipped: int = 0
    errors: list[str] = None

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []

    def to_dict(self) -> dict:
        return {
            "accounts": self.accounts,
            "positions_total": self.positions_total,
            "bonds_imported": self.bonds_imported,
            "bonds_updated": self.bonds_updated,
            "bonds_skipped": self.bonds_skipped,
            "errors": self.errors,
        }


def sync_tinkoff_portfolio(
    user: User,
    account_id: Optional[str] = None,
    sandbox: bool = False,
) -> dict:
    """Главная точка входа: синхронизация облигационного портфеля из T-Invest.

    Поведение:
      - читает зашифрованный токен пользователя;
      - получает список открытых счетов (или один указанный);
      - для каждого счёта берёт GetPortfolio, фильтрует bond-позиции;
      - обогащает названиями/тикерами через GetInstrumentBy;
      - upsert в BondPortfolio по (user_id, isin, is_sold=False);
      - обновляет last_price и tinkoff_last_sync_at.
    """
    if not user.tinkoff_token:
        return {"status": "error", "message": "Токен T-Invest не настроен."}

    try:
        plain_token = decrypt_token(user.tinkoff_token)
    except TInvestError as exc:
        return {"status": "error", "message": str(exc)}

    client = TInvestClient(token=plain_token, sandbox=sandbox)
    summary = SyncSummary()

    try:
        accounts = client.get_accounts()
    except TInvestAuthError as exc:
        return {"status": "error", "code": "auth", "message": str(exc)}
    except TInvestError as exc:
        return {"status": "error", "message": str(exc)}

    open_accounts = [a for a in accounts if a.get("status") == "ACCOUNT_STATUS_OPEN"]
    if account_id:
        open_accounts = [a for a in open_accounts if a.get("id") == account_id]
    if not open_accounts:
        return {"status": "error", "message": "Нет открытых счетов в T-Invest."}

    summary.accounts = len(open_accounts)

    for account in open_accounts:
        try:
            portfolio = client.get_portfolio(account["id"])
        except TInvestError as exc:
            summary.errors.append(f"Счёт {account.get('id')}: {exc}")
            continue

        positions = portfolio.get("positions", []) or []
        summary.positions_total += len(positions)
        bond_positions = [p for p in positions if p.get("instrumentType") == "bond"]

        figis = [p.get("figi") for p in bond_positions if p.get("figi")]
        instruments = client.batch_get_instruments(figis)

        for pos in bond_positions:
            figi = pos.get("figi")
            instr = instruments.get(figi) or {}
            isin = instr.get("isin")
            if not isin:
                summary.bonds_skipped += 1
                continue

            qty = int(quotation_to_decimal(pos.get("quantity")))
            if qty <= 0:
                summary.bonds_skipped += 1
                continue

            avg_rub_per_unit = _bond_buy_price_from_position(pos)
            cur_rub_per_unit = money_to_decimal(pos.get("currentPrice"))
            # MOEX-конвенция: цена в % от номинала. Номинал берём из инструмента,
            # дефолт 1000 руб. для рублёвых ОФЗ.
            face = money_to_decimal(instr.get("nominal")) or Decimal("1000")
            buy_pct = (avg_rub_per_unit / face * Decimal("100")).quantize(Decimal("0.01"))
            last_pct = (cur_rub_per_unit / face * Decimal("100")).quantize(Decimal("0.01"))

            existing = (
                BondPortfolio.query.filter_by(
                    user_id=user.id, isin=isin, is_sold=False
                ).first()
            )
            if existing:
                existing.amount = qty
                existing.buy_price = buy_pct
                existing.last_price = last_pct
                existing.name = instr.get("name") or existing.name
                existing.secid = instr.get("ticker") or existing.secid
                existing.currency = (instr.get("currency") or "rub").upper()
                summary.bonds_updated += 1
            else:
                db.session.add(
                    BondPortfolio(
                        user_id=user.id,
                        isin=isin,
                        secid=instr.get("ticker"),
                        name=instr.get("name"),
                        amount=qty,
                        buy_price=buy_pct,
                        last_price=last_pct,
                        purchase_date=date.today(),
                        is_sold=False,
                        currency=(instr.get("currency") or "rub").upper(),
                        notes=f"Импорт T-Invest, счёт {account.get('id')}",
                    )
                )
                summary.bonds_imported += 1

    user.tinkoff_last_sync_at = datetime.utcnow()
    if account_id:
        user.tinkoff_account_id = account_id
    db.session.commit()

    # Bust cache портфеля пользователя
    try:
        from app.blueprints.portfolio import _bust_user_cache
        _bust_user_cache(user.id)
    except Exception:  # pragma: no cover — кэш необязателен
        pass

    return {"status": "success", "message": "Портфель синхронизирован из T-Invest.", "summary": summary.to_dict()}


def unlink_user_token(user: User) -> None:
    """Удаляет привязку токена T-Invest у пользователя."""
    user.tinkoff_token = None
    user.tinkoff_account_id = None
    user.tinkoff_last_sync_at = None
    db.session.commit()


def link_user_token(user: User, plain_token: str, sandbox: bool = False) -> int:
    """Валидирует и сохраняет токен. Возвращает количество найденных счетов.

    Бросает ``TInvestAuthError`` если токен невалиден или ``TInvestError`` для других ошибок API.
    """
    accounts = verify_token(plain_token, sandbox=sandbox)
    user.tinkoff_token = encrypt_token(plain_token)
    db.session.commit()
    return len(accounts)


def list_accounts_for_user(user: User, sandbox: bool = False) -> dict:
    if not user.tinkoff_token:
        return {"status": "error", "message": "Токен T-Invest не настроен."}
    try:
        plain = decrypt_token(user.tinkoff_token)
        accounts = TInvestClient(token=plain, sandbox=sandbox).get_accounts()
    except TInvestAuthError as exc:
        return {"status": "error", "code": "auth", "message": str(exc)}
    except TInvestError as exc:
        return {"status": "error", "message": str(exc)}

    return {
        "status": "success",
        "accounts": [
            {
                "id": a.get("id"),
                "name": a.get("name"),
                "type": a.get("type"),
                "status": a.get("status"),
                "access_level": a.get("accessLevel"),
                "opened_date": (
                    timestamp_to_datetime(a.get("openedDate")).isoformat()
                    if a.get("openedDate")
                    else None
                ),
            }
            for a in accounts
        ],
    }

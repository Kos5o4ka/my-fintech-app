"""Курсы валют ЦБ РФ — простой клиент с in-process кэшем на 4 часа."""

import logging
import time

from defusedxml import ElementTree as ET  # nosec B405

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


@retry(
    retry=retry_if_exception_type(requests.RequestException),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
def _fetch_cbr_xml() -> bytes:
    """HTTP-запрос к ЦБ РФ с retry (3 попытки, экспоненциальная задержка 1-4с)."""
    resp = requests.get(_CBR_URL, timeout=8)
    resp.raise_for_status()
    return resp.content

# Коды валют, которые поддерживаем
_SUPPORTED = {"USD", "EUR", "GBP", "CNY", "CHF"}

_cache: dict[str, float] = {}  # {"USD": 90.25, ...}
_cache_ts: float = 0.0
_CACHE_TTL = 4 * 3600  # 4 часа

_CBR_URL = "https://www.cbr.ru/scripts/XML_daily.asp"


def get_rates(currencies: set[str] | None = None) -> dict[str, float]:
    """Возвращает {currency: rate_rub} для запрошенных валют.

    Кэш обновляется раз в 4 часа.  При ошибке возвращает последние
    известные значения (или пустой dict, если ещё не было успешного запроса).
    """
    global _cache, _cache_ts

    wanted = (currencies or _SUPPORTED) & _SUPPORTED

    now = time.monotonic()
    if now - _cache_ts < _CACHE_TTL and _cache:
        return {c: _cache[c] for c in wanted if c in _cache}

    try:
        content = _fetch_cbr_xml()
        root = ET.fromstring(content)
        new: dict[str, float] = {}
        for valute in root.findall("Valute"):
            char_code = valute.findtext("CharCode", "").strip().upper()
            if char_code not in _SUPPORTED:
                continue
            nominal_s = valute.findtext("Nominal", "1").strip().replace(",", ".")
            value_s = valute.findtext("Value", "0").strip().replace(",", ".")
            try:
                rate = float(value_s) / float(nominal_s)
                new[char_code] = round(rate, 4)
            except (ValueError, ZeroDivisionError):
                continue
        if new:
            _cache = new
            _cache_ts = now
    except Exception as exc:
        logger.warning("CBR rates fetch failed: %s", exc)

    return {c: _cache[c] for c in wanted if c in _cache}


def to_rub(amount: float, currency: str) -> float | None:
    """Конвертирует amount в RUB по курсу ЦБ.

    Возвращает None если курс неизвестен.
    """
    if currency == "RUB":
        return amount
    rates = get_rates({currency.upper()})
    rate = rates.get(currency.upper())
    return round(amount * rate, 2) if rate else None

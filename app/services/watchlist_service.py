"""Список наблюдения (watchlist).

Чисто CRUD + обогащение текущей ценой/YTM/НКД с MOEX.
"""

from __future__ import annotations

from app.exceptions import ConflictError, NotFoundError
from app.extensions import db
from app.models import Watchlist
from app.services.moex_service import get_bond_cached


def list_items(user_id: int) -> list[dict]:
    items = (
        Watchlist.query.filter_by(user_id=user_id)
        .order_by(Watchlist.added_at.desc())
        .all()
    )
    result = []
    for item in items:
        moex_data = get_bond_cached(item.isin) or {}
        result.append(
            {
                "isin": item.isin,
                "name": item.name or item.isin,
                "added_at": item.added_at.strftime("%Y-%m-%d"),
                "price": moex_data.get("price"),
                "ytm": moex_data.get("ytm"),
                "nkd": moex_data.get("nkd"),
            }
        )
    return result


def add_item(user_id: int, isin: str, secid: str, name: str) -> Watchlist:
    if Watchlist.query.filter_by(user_id=user_id, isin=isin).first():
        raise ConflictError("Облигация уже в списке наблюдения.")
    item = Watchlist(user_id=user_id, isin=isin, secid=secid, name=name)
    db.session.add(item)
    db.session.commit()
    return item


def remove_item(user_id: int, isin: str) -> None:
    item = Watchlist.query.filter_by(user_id=user_id, isin=isin).first()
    if not item:
        raise NotFoundError("Облигация не найдена в списке наблюдения.")
    db.session.delete(item)
    db.session.commit()


# ── Legacy facade (для обратной совместимости с portfolio_service) ───────────


def _legacy_add(user_id: int, isin: str, secid: str, name: str):
    """Старая сигнатура: None при успехе, str с ошибкой при дубликате."""
    try:
        add_item(user_id, isin, secid, name)
        return None
    except ConflictError as exc:
        return exc.message


def _legacy_remove(user_id: int, isin: str) -> bool:
    try:
        remove_item(user_id, isin)
        return True
    except NotFoundError:
        return False

"""Сервис ценовых алёртов."""

from __future__ import annotations

from app.exceptions import NotFoundError
from app.extensions import db
from app.models import PriceAlert


def list_alerts(user_id: int) -> list[dict]:
    alerts = (
        PriceAlert.query.filter_by(user_id=user_id)
        .order_by(PriceAlert.created_at.desc())
        .all()
    )
    return [
        {
            "id": a.id,
            "isin": a.isin,
            "name": a.name or a.isin,
            "target_price": float(a.target_price),
            "condition": a.condition,
            "is_triggered": a.is_triggered,
            "created_at": a.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }
        for a in alerts
    ]


def create_alert(
    user_id: int, isin: str, name: str, target_price: float, condition: str
) -> dict:
    new_alert = PriceAlert(
        user_id=user_id,
        isin=isin,
        name=name,
        target_price=target_price,
        condition=condition,
        is_triggered=False,
    )
    db.session.add(new_alert)
    db.session.commit()
    return {
        "id": new_alert.id,
        "isin": new_alert.isin,
        "name": new_alert.name,
        "target_price": target_price,
        "condition": new_alert.condition,
        "is_triggered": False,
    }


def delete_alert(alert_id: int, user_id: int) -> None:
    alert = PriceAlert.query.filter_by(id=alert_id, user_id=user_id).first()
    if not alert:
        raise NotFoundError("Алёрт не найден.")
    db.session.delete(alert)
    db.session.commit()


# ── Legacy facade ─────────────────────────────────────────────────────────────


def _legacy_delete(alert_id: int, user_id: int) -> bool:
    try:
        delete_alert(alert_id, user_id)
        return True
    except NotFoundError:
        return False

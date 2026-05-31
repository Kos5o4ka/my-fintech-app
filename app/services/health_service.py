"""Health-probe сервис и счётчик визитов.

Слой: blueprint → этот сервис → db / cache / внешние URL. Это позволяет
вызывать health-проверку из CLI / scheduled tasks без HTTP-контекста.
"""

from __future__ import annotations

import requests
from sqlalchemy import text

from app.extensions import cache, db
from app.models import Visit


def check_health() -> tuple[dict, int]:
    """Возвращает (status_dict, http_code). 200 при ok, 503 при degraded."""
    status: dict[str, str] = {}
    http_code = 200

    try:
        db.session.execute(text("SELECT 1"))
        status["db"] = "ok"
    except Exception as exc:  # pragma: no cover — зависит от внешнего ресурса
        status["db"] = str(exc)
        http_code = 503

    try:
        cache.set("_health_probe", "1", timeout=5)
        if cache.get("_health_probe") != "1":
            raise RuntimeError("cache read-back mismatch")
        status["cache"] = "ok"
    except Exception as exc:  # pragma: no cover
        status["cache"] = str(exc)
        http_code = 503

    try:
        resp = requests.get("https://iss.moex.com/iss/index.json", timeout=5)
        resp.raise_for_status()
        status["moex"] = "ok"
    except Exception as exc:  # pragma: no cover
        status["moex"] = f"unreachable: {exc}"

    overall = "ok" if http_code == 200 else "degraded"
    return ({"status": overall, **status}, http_code)


def increment_visit_counter() -> int:
    """Возвращает текущее значение счётчика после инкремента."""
    visit = Visit.query.first()
    if not visit:
        visit = Visit(count=1)
        db.session.add(visit)
    else:
        visit.count += 1
    db.session.commit()
    return visit.count

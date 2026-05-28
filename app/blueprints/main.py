from flask import Blueprint, render_template, jsonify, redirect, url_for
from flask_login import current_user, login_required
from sqlalchemy import text
from app.extensions import db, cache
from app.models import Visit

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index_page():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard_page"))
    return render_template("index.html")


@main_bp.route("/dashboard")
@login_required
def dashboard_page():
    return render_template("dashboard.html", active_page="dashboard")


@main_bp.route("/health")
def health_check():
    status = {}
    http_code = 200

    try:
        db.session.execute(text("SELECT 1"))
        status["db"] = "ok"
    except Exception as e:
        status["db"] = str(e)
        http_code = 503

    try:
        cache.set("_health_probe", "1", timeout=5)
        assert cache.get("_health_probe") == "1"
        status["cache"] = "ok"
    except Exception as e:
        status["cache"] = str(e)
        http_code = 503

    try:
        import requests as _req

        resp = _req.get("https://iss.moex.com/iss/index.json", timeout=5)
        resp.raise_for_status()
        status["moex"] = "ok"
    except Exception as e:
        status["moex"] = f"unreachable: {e}"

    return jsonify(
        {"status": "ok" if http_code == 200 else "degraded", **status}
    ), http_code


@main_bp.route("/api/init", methods=["GET"])
def get_initial_data():
    visit = Visit.query.first()
    if not visit:
        visit = Visit(count=1)
        db.session.add(visit)
    else:
        visit.count += 1
    db.session.commit()
    return jsonify(
        {
            "visits": visit.count,
            "is_authenticated": current_user.is_authenticated,
            "current_user": (
                {
                    "id": current_user.id,
                    "username": current_user.username,
                    "is_admin": current_user.is_admin,
                }
                if current_user.is_authenticated
                else None
            ),
        }
    )

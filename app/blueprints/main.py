from flask import Blueprint, jsonify, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.services.health_service import check_health, increment_visit_counter

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
    payload, http_code = check_health()
    return jsonify(payload), http_code


@main_bp.route("/api/init", methods=["GET"])
def get_initial_data():
    visits = increment_visit_counter()
    return jsonify(
        {
            "visits": visits,
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

from flask import Blueprint, render_template, jsonify
from flask_login import current_user
from extensions import db
from models import Visit

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index_page():
    return render_template("index.html")


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

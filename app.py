import csv
import logging
from io import StringIO
from datetime import datetime, date, timedelta
import requests
from collections import defaultdict
from flask import Flask, request, jsonify, render_template, abort, make_response
import re
from flask_cors import CORS
from flask_wtf import CSRFProtect
from flask_wtf.csrf import generate_csrf
import imghdr
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.exceptions import RequestEntityTooLarge
import os
from werkzeug.utils import secure_filename

from config import Config
from extensions import db, login_manager, migrate, cache, limiter
from models import User, BondPortfolio, Visit
from moex import get_moex_bond, get_bond_history_all, get_coupon_calendar
import math

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)
login_manager.init_app(app)
migrate.init_app(app, db)
cache.init_app(app, config={"CACHE_TYPE": "SimpleCache"})
csrf = CSRFProtect()
csrf.init_app(app)
limiter.init_app(app)

CORS(app, supports_credentials=True, origins=app.config["CORS_ORIGINS"])


@app.after_request
def set_security_headers(response):
    try:
        token = generate_csrf()
        response.set_cookie("XSRF-TOKEN", token, httponly=False, samesite="Lax")
    except Exception:
        pass
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self' cdn.jsdelivr.net 'unsafe-inline'; "
        "style-src 'self' cdn.jsdelivr.net 'unsafe-inline'; "
        "img-src 'self' data: ui-avatars.com; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'",
    )
    return response


def allowed_file(filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in app.config["ALLOWED_EXTENSIONS"]


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@app.errorhandler(400)
@app.errorhandler(401)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(413)
@app.errorhandler(500)
def handle_api_errors(error):
    if (
        request.path.startswith("/api/")
        or request.headers.get("Content-Type") == "application/json"
    ):
        message = (
            error.description
            if hasattr(error, "description")
            else "Внутренняя ошибка сервера"
        )
        if isinstance(error, RequestEntityTooLarge):
            message = "Загруженный файл слишком велик. Максимальный размер — 5 МБ."
        response = {
            "status": "error",
            "code": error.code if hasattr(error, "code") else 500,
            "message": message,
        }
        return jsonify(response), response["code"]

    if isinstance(error, RequestEntityTooLarge):
        return (
            render_template(
                "error.html",
                title="Файл слишком большой",
                message="Загруженный файл превышает допустимый размер 5 МБ.",
            ),
            413,
        )
    return error


@app.route("/")
def index_page():
    return render_template("index.html")


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile_page():
    if request.method == "POST":
        if "avatar" not in request.files:
            return jsonify({"status": "error", "message": "Нет файла."}), 400

        file = request.files["avatar"]
        if file.filename == "":
            return jsonify({"status": "error", "message": "Файл не выбран."}), 400

        if not allowed_file(file.filename):
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Недопустимый формат файла. Разрешены: PNG, JPG, GIF, WEBP.",
                    }
                ),
                400,
            )

        # Basic MIME/type validation using reported mimetype and file header
        if not file.mimetype or not file.mimetype.startswith("image"):
            return (
                jsonify(
                    {"status": "error", "message": "Файл не является изображением."}
                ),
                400,
            )

        header = file.read(512)
        file.seek(0)
        detected = imghdr.what(None, header)
        if detected is None:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Невозможно распознать формат изображения.",
                    }
                ),
                400,
            )

        filename = secure_filename(file.filename)
        unique_filename = f"user_{current_user.id}_{filename}"

        avatars_dir = app.config['UPLOAD_FOLDER']
        os.makedirs(avatars_dir, exist_ok=True)

        file_path = os.path.join(avatars_dir, unique_filename)
        file.save(file_path)

        current_user.avatar = unique_filename
        db.session.commit()

    # Передаём CSRF токен в форму (для неподключённого JS)
    return render_template("profile.html", csrf_token=generate_csrf())


@app.route("/api/init", methods=["GET"])
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


@app.route("/api/portfolio", methods=["GET"])
@login_required
def get_portfolio():
    active_bonds = BondPortfolio.query.filter_by(
        user_id=current_user.id, is_sold=False
    ).all()
    portfolio_list = []
    total_portfolio_value = 0.0
    for bond in active_bonds:
        current_price = (
            float(bond.last_price)
            if bond.last_price is not None
            else float(bond.buy_price)
        )
        current_value = bond.amount * current_price
        total_portfolio_value += current_value

        moex_data = get_moex_bond(bond.isin) or {}
        portfolio_list.append(
            {
                "id": bond.id,
                "isin": bond.isin,
                "name": bond.name or "Облигация",
                "amount": bond.amount,
                "buy_price": float(bond.buy_price),
                "last_price": float(bond.last_price) if bond.last_price else None,
                "current_value": current_value,
                "purchase_date": bond.purchase_date.strftime("%Y-%m-%d"),
                "nkd": moex_data.get("nkd", 0.0),
                "ytm": moex_data.get("ytm", 0.0),
            }
        )
    return jsonify(
        {
            "status": "success",
            "total_value": total_portfolio_value,
            "bonds": portfolio_list,
        }
    )


@app.route("/api/add_bond", methods=["POST"])
@login_required
def add_bond():
    data = request.get_json() or {}
    isin = data.get("isin", "").upper().strip()
    amount = data.get("amount")
    buy_price = data.get("buy_price")
    date_str = data.get("purchase_date", "").strip()

    if not all([isin, amount, buy_price]):
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Все поля формы обязательны к заполнению.",
                }
            ),
            400,
        )

    try:
        purchase_date = (
            datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else date.today()
        )
    except ValueError:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Неверный формат даты. Используйте ГГГГ-ММ-ДД.",
                }
            ),
            400,
        )

    moex_data = get_moex_bond(isin)
    if not moex_data:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": f"Облигация {isin} не найдена на Московской Бирже.",
                }
            ),
            404,
        )

    secid = moex_data["secid"]
    bond_title = moex_data.get("name", "Облигация")

    try:
        url = f"https://iss.moex.com/iss/securities/{secid}.json"
        res = requests.get(url, timeout=5).json()
        if res.get("description") and res["description"].get("data"):
            desc_data = res["description"]["data"]
            issue_date, mat_date = None, None
            for row in desc_data:
                if row[0] == "ISSUEDATE" and row[2]:
                    issue_date = datetime.strptime(row[2], "%Y-%m-%d").date()
                if row[0] == "MATDATE" and row[2]:
                    mat_date = datetime.strptime(row[2], "%Y-%m-%d").date()

            if issue_date and purchase_date < issue_date:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": f"Ошибка валидации: облигация выпущена {issue_date}. Нельзя купить бумагу до эмиссии.",
                        }
                    ),
                    400,
                )
            if mat_date and purchase_date > mat_date:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": f"Ошибка валидации: облигация погашена {mat_date}. Торги закрыты.",
                        }
                    ),
                    400,
                )
    except Exception as e:
        logger.warning("Date spec validation error for %s: %s", secid, e)

    live_price = moex_data.get("price", float(buy_price))
    new_bond = BondPortfolio(
        user_id=current_user.id,
        isin=isin,
        secid=secid,
        name=bond_title,
        amount=int(amount),
        buy_price=float(buy_price),
        last_price=live_price,
        purchase_date=purchase_date,
        is_sold=False,
    )
    db.session.add(new_bond)
    db.session.commit()
    return (
        jsonify(
            {"status": "success", "message": f"Бумага {bond_title} успешно добавлена!"}
        ),
        201,
    )


@app.route("/api/bond_chart/<isin>", methods=["GET"])
@login_required
def get_bond_chart_data(isin):
    # Поддерживаем параметр range=day|week|month|all и серверный downsampling
    range_param = request.args.get("range", "all")
    cache_key = f"bond_chart:{isin}:{range_param}"
    cached = cache.get(cache_key)
    if cached:
        return jsonify(cached)

    moex_data = get_moex_bond(isin)
    if not moex_data:
        return jsonify({"status": "error", "message": "Бумага не найдена"}), 404

    full = get_bond_history_all(moex_data["secid"], moex_data.get("facevalue", 1000))
    labels = full.get("labels", [])
    prices = full.get("data", [])
    nkd_hist = full.get("nkd", [])
    ytm_hist = full.get("ytm", [])

    # Фильтрация по диапазону (по датам)
    if range_param in ("day", "week", "month"):
        days_map = {"day": 1, "week": 7, "month": 31}
        days = days_map.get(range_param, 31)
        cutoff = datetime.utcnow().date() - timedelta(days=days)
        combined = []
        for l, p, n, y in zip(labels, prices, nkd_hist, ytm_hist):
            try:
                d = datetime.strptime(l, "%Y-%m-%d").date()
            except Exception:
                continue
            if d >= cutoff:
                combined.append((l, p, n, y))
        # Если после фильтрации пусто — вернуть последние N точек
        if not combined:
            take = min(100, len(labels))
            combined = list(
                zip(labels[-take:], prices[-take:], nkd_hist[-take:], ytm_hist[-take:])
            )
    else:
        combined = list(zip(labels, prices, nkd_hist, ytm_hist))

    # Downsample: ограничим количество точек (например, 800)
    max_points = 800
    if len(combined) > max_points:
        step = math.ceil(len(combined) / max_points)
        combined = [combined[i] for i in range(0, len(combined), step)]

    if combined:
        labels_out, prices_out, nkd_out, ytm_out = zip(*combined)
        result = {
            "labels": list(labels_out),
            "data": list(prices_out),
            "nkd": list(nkd_out),
            "ytm": list(ytm_out),
        }
    else:
        result = {"labels": [], "data": [], "nkd": [], "ytm": []}

    # Кэшировать результат (короткий TTL для частых запросов)
    ttl = 300 if range_param != "all" else 1800
    try:
        cache.set(cache_key, result, timeout=ttl)
    except Exception:
        pass

    return jsonify(result)


@app.route("/api/portfolio/calendar", methods=["GET"])
@login_required
def get_portfolio_calendar():
    active_bonds = BondPortfolio.query.filter_by(
        user_id=current_user.id, is_sold=False
    ).all()
    events = []
    for bond in active_bonds:
        target = bond.secid or bond.isin
        coupons = get_coupon_calendar(target)
        for c in coupons:
            events.append(
                {
                    "name": bond.name or bond.isin,
                    "isin": bond.isin,
                    "date": c["date"],
                    "total_payout": round(c["value"] * bond.amount, 2),
                }
            )
    events.sort(key=lambda x: x["date"])
    return jsonify(events[:10])


@app.route("/api/portfolio/export", methods=["GET"])
@login_required
def export_portfolio_csv():
    active_bonds = BondPortfolio.query.filter_by(
        user_id=current_user.id, is_sold=False
    ).all()
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(
        [
            "Название бумаги",
            "ISIN код",
            "Количество (шт)",
            "Цена покупки (руб)",
            "Дата сделки",
        ]
    )
    for bond in active_bonds:
        cw.writerow(
            [bond.name, bond.isin, bond.amount, bond.buy_price, bond.purchase_date]
        )
    response = make_response('﻿' + si.getvalue())
    response.headers["Content-Disposition"] = (
        "attachment; filename=portfolio_report.csv"
    )
    response.headers["Content-Type"] = "text/csv; charset=utf-8-sig"
    return response


@app.route("/api/sell_bond/<int:bond_id>", methods=["POST"])
@login_required
def sell_bond(bond_id):
    bond = db.session.get(BondPortfolio, bond_id)
    if bond is None:
        abort(404)
    if bond.user_id != current_user.id:
        abort(403)

    data = request.get_json() or {}
    sell_price_raw = data.get("sell_price")
    bond.is_sold = True
    bond.sell_date = date.today()
    bond.sell_price = (
        float(sell_price_raw)
        if sell_price_raw
        else (float(bond.last_price) if bond.last_price else float(bond.buy_price))
    )
    db.session.commit()
    return jsonify(
        {
            "status": "success",
            "message": f"Облигация {bond.name} переведена в архив продаж.",
        }
    )


@app.route("/api/portfolio_stats", methods=["GET"])
@login_required
def portfolio_stats():
    closed_deals = BondPortfolio.query.filter_by(
        user_id=current_user.id, is_sold=True
    ).all()
    monthly_profit = defaultdict(float)
    for bond in closed_deals:
        sell_p = (
            float(bond.sell_price)
            if bond.sell_price
            else (float(bond.last_price) if bond.last_price else float(bond.buy_price))
        )
        group_date = bond.sell_date or bond.purchase_date
        monthly_profit[group_date.strftime("%Y-%m")] += (
            sell_p - float(bond.buy_price)
        ) * bond.amount
    sorted_months = sorted(monthly_profit.keys())
    return jsonify(
        {
            "labels": sorted_months,
            "datasets": [
                {
                    "label": "Чистая зафиксированная прибыль (₽)",
                    "data": [monthly_profit[m] for m in sorted_months],
                    "backgroundColor": "rgba(40, 167, 69, 0.2)",
                    "borderColor": "rgba(40, 167, 69, 1)",
                    "borderWidth": 2,
                    "fill": True,
                }
            ],
        }
    )


@app.route("/api/auth/login", methods=["POST"])
@limiter.limit("10 per minute")
def api_login():
    data = request.get_json() or {}
    user = User.query.filter_by(username=data.get("username", "").strip()).first()
    if not user or not check_password_hash(
        user.password_hash, data.get("password", "").strip()
    ):
        return (
            jsonify({"status": "error", "message": "Неверный логин или пароль."}),
            401,
        )
    login_user(user, remember=True)
    return jsonify(
        {
            "status": "success",
            "user": {
                "id": user.id,
                "username": user.username,
                "is_admin": user.is_admin,
            },
        }
    )


@app.route("/api/auth/logout", methods=["POST", "GET"])
def api_logout():
    logout_user()
    return jsonify({"status": "success", "message": "Вы успешно вышли из системы."})


@app.route("/api/admin/users", methods=["GET"])
@login_required
def get_all_users():
    if not current_user.is_admin:
        abort(403)
    users = User.query.all()
    return jsonify(
        [{"id": u.id, "username": u.username, "is_admin": u.is_admin} for u in users]
    )


@app.route("/api/admin/add_user", methods=["POST"])
@login_required
@limiter.limit("30 per hour")
def admin_add_user():
    if not current_user.is_admin:
        abort(403)

    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    is_admin = data.get("is_admin", False)

    if not username or not password:
        return (
            jsonify({"status": "error", "message": "Логин и пароль обязательны."}),
            400,
        )

    # Username validation: only ASCII letters and digits, length 3-20
    if not re.fullmatch(r"[A-Za-z0-9]{3,20}", username):
        return (
            jsonify({"status": "error", "message": "Логин должен содержать только латинские буквы и цифры, 3–20 символов."}),
            400,
        )

    if User.query.filter_by(username=username).first():
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Пользователь с таким логином уже существует.",
                }
            ),
            400,
        )

    new_user = User(
        username=username,
        password_hash=generate_password_hash(password),
        is_admin=is_admin,
    )
    db.session.add(new_user)
    db.session.commit()
    # Return credentials so admin can copy them — only in admin UI context
    return (
        jsonify(
            {
                "status": "success",
                "message": f"Пользователь {username} успешно создан!",
                "user_id": new_user.id,
            }
        ),
        201,
    )


@app.route("/api/admin/delete_user/<int:user_id>", methods=["DELETE"])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        abort(403)

    user_to_delete = db.session.get(User, user_id)
    if user_to_delete is None:
        abort(404)
    if user_to_delete.id == current_user.id:
        return (
            jsonify({"status": "error", "message": "Вы не можете удалить сами себя."}),
            400,
        )

    db.session.delete(user_to_delete)
    db.session.commit()
    return jsonify(
        {
            "status": "success",
            "message": f"Пользователь {user_to_delete.username} удален.",
        }
    )


@app.route("/portfolio")
@login_required
def portfolio_page():
    return render_template("portfolio.html")


if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug_mode, port=5000)

import csv
from io import StringIO
from datetime import datetime, date
import requests
from collections import defaultdict
from flask import Flask, request, jsonify, render_template, abort, make_response
from flask_cors import CORS
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash  # ИСПРАВЛЕННЫЙ ИМПОРТ
import os
from werkzeug.utils import secure_filename

from config import Config
from extensions import db, login_manager, migrate
from models import User, BondPortfolio, Visit
from moex import get_moex_bond, get_bond_history_all, get_coupon_calendar

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)
login_manager.init_app(app)
migrate.init_app(app, db)

CORS(app, supports_credentials=True,
     origins=["http://127.0.0.1:5000", "http://localhost:5000", "http://194.50.94.45:5000"])


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.errorhandler(400)
@app.errorhandler(401)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(500)
def handle_api_errors(error):
    if request.path.startswith('/api/') or request.headers.get('Content-Type') == 'application/json':
        response = {
            "status": "error",
            "code": error.code if hasattr(error, 'code') else 500,
            "message": error.description if hasattr(error, 'description') else "Внутренняя ошибка сервера"
        }
        return jsonify(response), response["code"]
    return error


@app.route('/')
def index_page(): return render_template('index.html')


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile_page():
    if request.method == 'POST':
        if 'avatar' not in request.files:
            return jsonify({"status": "error", "message": "Нет файла."}), 400

        file = request.files['avatar']
        if file.filename == '':
            return jsonify({"status": "error", "message": "Файл не выбран."}), 400

        if file:
            filename = secure_filename(file.filename)
            # Генерируем уникальное имя файла, чтобы избежать перезаписи
            unique_filename = f"user_{current_user.id}_{filename}"

            # Убеждаемся, что папка существует
            avatars_dir = os.path.join(app.root_path, 'static', 'avatars')
            os.makedirs(avatars_dir, exist_ok=True)

            file_path = os.path.join(avatars_dir, unique_filename)
            file.save(file_path)

            # Обновляем базу данных
            current_user.avatar = unique_filename
            db.session.commit()

    return render_template('profile.html')


@app.route('/api/init', methods=['GET'])
def get_initial_data():
    visit = Visit.query.first()
    if not visit:
        visit = Visit(count=1);
        db.session.add(visit)
    else:
        visit.count += 1
    db.session.commit()
    return jsonify({"visits": visit.count, "is_authenticated": current_user.is_authenticated,
                    "current_user": {"id": current_user.id, "username": current_user.username,
                                     "is_admin": current_user.is_admin} if current_user.is_authenticated else None})


@app.route('/api/portfolio', methods=['GET'])
@login_required
def get_portfolio():
    active_bonds = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=False).all()
    portfolio_list = []
    total_portfolio_value = 0.0
    for bond in active_bonds:
        current_price = float(bond.last_price) if bond.last_price is not None else float(bond.buy_price)
        current_value = bond.amount * current_price
        total_portfolio_value += current_value

        moex_data = get_moex_bond(bond.isin) or {}
        portfolio_list.append({
            "id": bond.id, "isin": bond.isin, "name": bond.name or "Облигация",
            "amount": bond.amount, "buy_price": float(bond.buy_price),
            "last_price": float(bond.last_price) if bond.last_price else None,
            "current_value": current_value, "purchase_date": bond.purchase_date.strftime('%Y-%m-%d'),
            "nkd": moex_data.get('nkd', 0.0), "ytm": moex_data.get('ytm', 0.0)
        })
    return jsonify({"status": "success", "total_value": total_portfolio_value, "bonds": portfolio_list})


@app.route('/api/add_bond', methods=['POST'])
@login_required
def add_bond():
    data = request.get_json() or {}
    isin = data.get('isin', '').upper().strip()
    amount = data.get('amount')
    buy_price = data.get('buy_price')
    date_str = data.get('purchase_date', '').strip()

    if not all([isin, amount, buy_price]):
        return jsonify({"status": "error", "message": "Все поля формы обязательны к заполнению."}), 400

    purchase_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else date.today()

    moex_data = get_moex_bond(isin)
    if not moex_data:
        return jsonify({"status": "error", "message": f"Облигация {isin} не найдена на Московской Бирже."}), 404

    secid = moex_data['secid']
    bond_title = moex_data.get('name', 'Облигация')

    try:
        url = f"https://iss.moex.com/iss/securities/{secid}.json"
        res = requests.get(url, timeout=5).json()
        if res.get('description') and res['description'].get('data'):
            desc_data = res['description']['data']
            issue_date, mat_date = None, None
            for row in desc_data:
                if row[0] == 'ISSUEDATE' and row[2]: issue_date = datetime.strptime(row[2], '%Y-%m-%d').date()
                if row[0] == 'MATDATE' and row[2]: mat_date = datetime.strptime(row[2], '%Y-%m-%d').date()

            if issue_date and purchase_date < issue_date:
                return jsonify({"status": "error",
                                "message": f"Ошибка валидации: облигация выпущена {issue_date}. Нельзя купить бумагу до эмиссии."}), 400
            if mat_date and purchase_date > mat_date:
                return jsonify({"status": "error",
                                "message": f"Ошибка валидации: облигация погашена {mat_date}. Торги закрыты."}), 400
    except Exception as e:
        print(f"Ошибка проверки дат спецификации: {e}")

    live_price = moex_data.get('price', float(buy_price))
    new_bond = BondPortfolio(user_id=current_user.id, isin=isin, name=bond_title, amount=int(amount),
                             buy_price=float(buy_price), last_price=live_price, purchase_date=purchase_date,
                             is_sold=False)
    db.session.add(new_bond)
    db.session.commit()
    return jsonify({"status": "success", "message": f"Бумага {bond_title} успешно добавлена!"}), 201


@app.route('/api/bond_chart/<isin>', methods=['GET'])
@login_required
def get_bond_chart_data(isin):
    moex_data = get_moex_bond(isin)
    if not moex_data: return jsonify({"status": "error", "message": "Бумага не найдена"}), 404
    return jsonify(get_bond_history_all(moex_data['secid']))


@app.route('/api/portfolio/calendar', methods=['GET'])
@login_required
def get_portfolio_calendar():
    active_bonds = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=False).all()
    events = []
    for bond in active_bonds:
        coupons = get_coupon_calendar(bond.isin)
        for c in coupons:
            events.append({"name": bond.name or bond.isin, "isin": bond.isin, "date": c["date"],
                           "total_payout": round(c["value"] * bond.amount, 2)})
    events.sort(key=lambda x: x["date"])
    return jsonify(events[:10])


@app.route('/api/portfolio/export', methods=['GET'])
@login_required
def export_portfolio_csv():
    active_bonds = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=False).all()
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['Название бумаги', 'ISIN код', 'Количество (шт)', 'Цена покупки (руб)', 'Дата сделки'])
    for bond in active_bonds: cw.writerow([bond.name, bond.isin, bond.amount, bond.buy_price, bond.purchase_date])
    response = make_response(si.getvalue())
    response.headers['Content-Disposition'] = 'attachment; filename=portfolio_report.csv'
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    return response


@app.route('/api/sell_bond/<int:bond_id>', methods=['POST'])
@login_required
def sell_bond(bond_id):
    bond = BondPortfolio.query.get_or_404(bond_id)
    if bond.user_id != current_user.id: abort(403)
    bond.is_sold = True;
    db.session.commit()
    return jsonify({"status": "success", "message": f"Облигация {bond.name} переведена в архив продаж."})


@app.route('/api/portfolio_stats', methods=['GET'])
@login_required
def portfolio_stats():
    closed_deals = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=True).all()
    monthly_profit = defaultdict(float)
    for bond in closed_deals:
        if bond.last_price is not None: monthly_profit[bond.purchase_date.strftime('%Y-%m')] += (float(
            bond.last_price) - float(bond.buy_price)) * bond.amount
    sorted_months = sorted(monthly_profit.keys())
    return jsonify({"labels": sorted_months, "datasets": [
        {"label": "Чистая зафиксированная прибыль (₽)", "data": [monthly_profit[m] for m in sorted_months],
         "backgroundColor": "rgba(40, 167, 69, 0.2)", "borderColor": "rgba(40, 167, 69, 1)", "borderWidth": 2,
         "fill": True}]})


@app.route('/api/auth/login', methods=['POST'])
def api_login():
    data = request.get_json() or {}
    user = User.query.filter_by(username=data.get('username', '').strip()).first()
    if not user or not check_password_hash(user.password_hash, data.get('password', '').strip()): return jsonify(
        {"status": "error", "message": "Неверный логин или пароль."}), 401
    login_user(user, remember=True)
    return jsonify({"status": "success", "user": {"id": user.id, "username": user.username, "is_admin": user.is_admin}})


@app.route('/api/auth/logout', methods=['POST', 'GET'])
def api_logout(): logout_user(); return jsonify({"status": "success", "message": "Вы успешно вышли из системы."})


@app.route('/api/admin/users', methods=['GET'])
@login_required
def get_all_users():
    if not current_user.is_admin:
        abort(403)  # Доступ запрещен для обычных юзеров
    users = User.query.all()
    users_data = [{"id": u.id, "username": u.username, "is_admin": u.is_admin} for u in users]
    return jsonify(users_data)


@app.route('/api/admin/add_user', methods=['POST'])
@login_required
def admin_add_user():
    if not current_user.is_admin:
        abort(403)

    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    is_admin = data.get('is_admin', False)

    if not username or not password:
        return jsonify({"status": "error", "message": "Логин и пароль обязательны."}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({"status": "error", "message": "Пользователь с таким логином уже существует."}), 400

    new_user = User(
        username=username,
        password_hash=generate_password_hash(password),
        is_admin=is_admin
    )
    db.session.add(new_user)
    db.session.commit()

    return jsonify({"status": "success", "message": f"Пользователь {username} успешно создан!"}), 201


@app.route('/api/admin/delete_user/<int:user_id>', methods=['DELETE'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        abort(403)

    user_to_delete = User.query.get_or_404(user_id)
    if user_to_delete.id == current_user.id:
        return jsonify({"status": "error", "message": "Вы не можете удалить сами себя."}), 400

    db.session.delete(user_to_delete)
    db.session.commit()
    return jsonify({"status": "success", "message": f"Пользователь {user_to_delete.username} удален."})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
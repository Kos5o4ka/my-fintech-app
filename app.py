import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from dotenv import load_dotenv
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename 
from flask_login import login_user, login_required, logout_user, current_user
from apscheduler.schedulers.background import BackgroundScheduler # Планировщик для фоновых задач

# Импорты из твоих модулей
from extensions import db, login_manager, cache, migrate
from models import Visit, User, BondPortfolio
from moex import get_moex_bond

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'super-secret-key-change-me-later')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/avatars'

# Настройка кэширования
app.config['CACHE_TYPE'] = 'SimpleCache'
app.config['CACHE_DEFAULT_TIMEOUT'] = 600

# Инициализация расширений
db.init_app(app)
login_manager.init_app(app)
cache.init_app(app)
migrate.init_app(app, db) # Инициализация миграций 

login_manager.login_view = 'index'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- ФОНОВАЯ ЗАДАЧА: ОБНОВЛЕНИЕ ЦЕН В БАЗЕ ---
def update_bond_prices():
    """Раз в 10 минут обновляет цены всех активных облигаций в БД"""
    with app.app_context():
        # Берем только те бумаги, которые еще не проданы
        active_bonds = BondPortfolio.query.filter_by(is_sold=False).all()
        unique_isins = {b.isin for b in active_bonds}
        
        for isin in unique_isins:
            data = get_moex_bond(isin)
            if data:
                # Обновляем кэш цены в базе для всех записей с этим ISIN
                BondPortfolio.query.filter_by(isin=isin, is_sold=False).update({
                    'last_price': data['price'],
                    'last_updated': datetime.now()
                })
        db.session.commit()
        print(f"[{datetime.now()}] Цены в базе данных успешно обновлены из MOEX.")

# Настройка и запуск планировщика 
scheduler = BackgroundScheduler()
scheduler.add_job(func=update_bond_prices, trigger="interval", minutes=10)
scheduler.start()

# Вспомогательная функция для аватарок
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ==========================================
# API МАРШРУТЫ (JSON)
# ==========================================

@app.route('/api/portfolio_stats')
@login_required
@cache.cached(timeout=600)
def api_portfolio_stats():
    bonds = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=False).all()
    grouped = {}
    for b in bonds:
        if b.isin not in grouped: grouped[b.isin] = {'amount': 0}
        grouped[b.isin]['amount'] += b.amount
    stats = []
    for isin, g in grouped.items():
        data = get_moex_bond(isin)
        if data:
            val = (data['price'] + data['nkd']) * g['amount']
            stats.append({'name': data['name'], 'value': round(val, 2)})
    return jsonify(stats)

@app.route('/api/sell_bond/<int:bond_id>', methods=['POST'])
@login_required
def sell_bond(bond_id):
    """API для продажи облигации и фиксации прибыли """
    bond = BondPortfolio.query.get_or_404(bond_id)
    if bond.user_id != current_user.id:
        return jsonify({"error": "Доступ запрещен"}), 403
    
    data = request.json
    try:
        sell_price = float(data.get('sell_price'))
        bond.is_sold = True
        bond.sell_price = sell_price
        bond.sell_date = datetime.now().date()
        # Считаем реализованную прибыль
        bond.realized_profit = (sell_price - bond.buy_price) * bond.amount
        
        db.session.commit()
        return jsonify({"status": "success", "profit": round(bond.realized_profit, 2)})
    except (TypeError, ValueError):
        return jsonify({"error": "Некорректная цена"}), 400

@app.route('/api/coupons/<secid>')
@login_required
def api_coupons(secid):
    import requests
    url = f"https://iss.moex.com/iss/securities/{secid}/bondization.json?limit=100"
    try:
        res = requests.get(url, timeout=5).json()
        data, cols = res['coupons']['data'], res['coupons']['columns']
        today = datetime.now().strftime('%Y-%m-%d')
        coupons = [{'date': r[cols.index('coupondate')], 'value': r[cols.index('value')]} for r in data]
        return jsonify({"past": [c for c in coupons if c['date'] < today], "future": [c for c in coupons if c['date'] >= today]})
    except: return jsonify({"error": "Ошибка API MOEX"})

# ==========================================
# ОСНОВНЫЕ СТРАНИЦЫ (HTML)
# ==========================================

@app.route('/', methods=['GET', 'POST'])
def index():
    v = Visit.query.first()
    if not v:
        v = Visit(count=1); db.session.add(v)
    else: v.count += 1
    db.session.commit()
    
    if request.method == 'POST' and not current_user.is_authenticated:
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and check_password_hash(user.password_hash, request.form.get('password')):
            login_user(user); return redirect(url_for('index'))
        flash('Ошибка входа', 'danger')
        
    users = User.query.all() if current_user.is_authenticated and current_user.is_admin else []
    return render_template('index.html', visits=v.count, users=users)

@app.route('/portfolio')
@login_required
def portfolio():
    # Показываем только не проданные бумаги
    bonds = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=False).all()
    grouped, total_invested, total_current = {}, 0, 0
    
    for b in bonds:
        if b.isin not in grouped: 
            grouped[b.isin] = {'isin': b.isin, 'total_amount': 0, 'total_invested': 0.0, 'transactions': []}
        grouped[b.isin]['total_amount'] += b.amount
        inv = b.buy_price * b.amount
        grouped[b.isin]['total_invested'] += inv
        total_invested += inv
        grouped[b.isin]['transactions'].append(b)
        
    items = []
    for isin, g in grouped.items():
        moex = get_moex_bond(isin)
        avg = g['total_invested'] / g['total_amount']
        g['transactions'].sort(key=lambda x: x.purchase_date or datetime.min.date(), reverse=True)
        
        if moex:
            val = (moex['price'] + moex['nkd']) * g['total_amount']
            total_current += val
            items.append({
                'isin': isin, 'secid': moex['secid'], 'name': moex['name'], 
                'amount': g['total_amount'], 'avg_buy_price': round(avg, 2), 
                'current_price': moex['price'], 'nkd': moex['nkd'], 'coupon': moex['coupon'], 
                'profit': round(val - g['total_invested'], 2), 'transactions': g['transactions']
            })
        else:
            items.append({'isin': isin, 'name': 'Ошибка MOEX', 'amount': g['total_amount'], 'avg_buy_price': round(avg, 2), 'transactions': g['transactions']})
            
    return render_template('portfolio.html', items=items, 
                           total_invested=round(total_invested, 2), 
                           total_current=round(total_current, 2), 
                           total_profit=round(total_current - total_invested, 2), 
                           today_date=datetime.now().strftime('%Y-%m-%d'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST' and 'avatar' in request.files:
        file = request.files['avatar']
        if file and allowed_file(file.filename):
            fname = secure_filename(file.filename)
            uname = f"user_{current_user.id}_{fname}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], uname))
            current_user.avatar = uname
            db.session.commit()
            flash('Аватар обновлен', 'success')
    return render_template('profile.html')

@app.route('/add_bond', methods=['POST'])
@login_required
def add_bond():
    isin = request.form.get('isin').strip().upper()
    if get_moex_bond(isin):
        new_b = BondPortfolio(
            user_id=current_user.id, 
            isin=isin, 
            amount=int(request.form.get('amount')), 
            buy_price=float(request.form.get('buy_price')), 
            purchase_date=datetime.strptime(request.form.get('purchase_date'), '%Y-%m-%d').date()
        )
        db.session.add(new_b)
        db.session.commit()
        flash('Бумага успешно добавлена', 'success')
    else:
        flash('Бумага не найдена на MOEX', 'danger')
    return redirect(url_for('portfolio'))

@app.route('/delete_bond/<int:bond_id>')
@login_required
def delete_bond(bond_id):
    b = BondPortfolio.query.get(bond_id)
    if b and b.user_id == current_user.id:
        db.session.delete(b)
        db.session.commit()
    return redirect(url_for('portfolio'))

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

if __name__ == '__main__':
    # В промышленной среде (через Gunicorn) этот блок не используется,
    # но полезен для локальной отладки.
    app.run(host='0.0.0.0')
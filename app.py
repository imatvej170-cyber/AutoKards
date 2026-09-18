from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash, Response, jsonify)
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import psycopg2
import psycopg2.extras
import os
import random
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-me-please')

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    raise RuntimeError('Не найдена переменная DATABASE_URL.')

DATABASE_URL = DATABASE_URL.replace('?sslmode=require', '').replace('&sslmode=require', '')

app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024

# ============ ЭКОНОМИКА ============
START_BALANCE = 500
DAILY_BONUS = 100
SELL_RATE = 0.7
BONUS_COOLDOWN = 86400

# ============ КТО АДМИН ============
ADMIN_USERNAMES = {'AppleAT'}


# ---------- НАСТРОЙКИ ПО УМОЛЧАНИЮ ----------
DEFAULT_SETTINGS = {
    # Скидка дня
    'discount_enabled': '1',
    'discount_min_rating': '1',
    'discount_max_rating': '3',
    'discount_percent': '50',
    # Колесо фортуны
    'wheel_enabled': '1',
    'wheel_coin_min': '50',
    'wheel_coin_max': '500',
    'wheel_car_chance': '10',      # в процентах
    'wheel_car_min_rating': '1',
    'wheel_car_max_rating': '5',
    'wheel_cooldown_hours': '24',
}


# ---------- БАЗА ----------
def get_db():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username VARCHAR(20) UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    )''')
    c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_data BYTEA')
    c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_mime TEXT')
    c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS bio TEXT')
    c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS favorite_car_id INTEGER')
    c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS balance INTEGER')
    c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS last_bonus_at TEXT')
    c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS last_spin_at TEXT')

    c.execute('''CREATE TABLE IF NOT EXISTS cars (
        id SERIAL PRIMARY KEY,
        model VARCHAR(60) NOT NULL,
        rating INTEGER NOT NULL,
        image_data BYTEA NOT NULL,
        image_mime TEXT NOT NULL,
        created_at TEXT NOT NULL
    )''')
    c.execute('ALTER TABLE cars ADD COLUMN IF NOT EXISTS price INTEGER')

    c.execute('''CREATE TABLE IF NOT EXISTS user_cars (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        car_id INTEGER NOT NULL,
        opened_at TEXT NOT NULL,
        UNIQUE(user_id, car_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS public_cars (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        car_id INTEGER NOT NULL,
        UNIQUE(user_id, car_id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS daily_discount (
        id SERIAL PRIMARY KEY,
        car_id INTEGER NOT NULL,
        discount_percent INTEGER NOT NULL,
        set_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        type VARCHAR(30) NOT NULL,
        amount INTEGER NOT NULL DEFAULT 0,
        car_id INTEGER,
        description TEXT NOT NULL,
        created_at TEXT NOT NULL
    )''')

    c.execute('UPDATE users SET balance = %s WHERE balance IS NULL', (START_BALANCE,))
    c.execute('UPDATE cars SET price = 500 WHERE price IS NULL')

    # Заполняем настройки по умолчанию
    for k, v in DEFAULT_SETTINGS.items():
        c.execute('INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING',
                  (k, v))

    conn.commit()
    c.close()
    conn.close()


# ---------- НАСТРОЙКИ ----------
def get_setting(key, default=None):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT value FROM settings WHERE key = %s', (key,))
    row = c.fetchone()
    c.close()
    conn.close()
    if row:
        return row[0]
    return default if default is not None else DEFAULT_SETTINGS.get(key)


def get_int_setting(key, default=0):
    try:
        return int(get_setting(key))
    except (ValueError, TypeError):
        return default


def set_setting(key, value):
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO settings (key, value) VALUES (%s, %s) '
              'ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value', (key, str(value)))
    conn.commit()
    c.close()
    conn.close()


# ---------- ПОЛЬЗОВАТЕЛИ ----------
def get_user(username):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, username, password_hash FROM users WHERE username = %s', (username,))
    row = c.fetchone()
    c.close()
    conn.close()
    return row


def create_user(username, password):
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO users (username, password_hash, created_at, balance) '
              'VALUES (%s, %s, %s, %s)',
              (username, generate_password_hash(password), datetime.now().isoformat(),
               START_BALANCE))
    conn.commit()
    c.close()
    conn.close()


def get_user_profile(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT id, username, avatar_data, avatar_mime, bio, favorite_car_id, balance
                 FROM users WHERE id = %s''', (user_id,))
    row = c.fetchone()
    c.close()
    conn.close()
    if not row:
        return None
    return {
        'id': row[0], 'username': row[1], 'avatar_data': row[2], 'avatar_mime': row[3],
        'bio': row[4], 'favorite_car_id': row[5], 'balance': row[6] or 0,
    }


def update_profile(user_id, bio, favorite_car_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE users SET bio = %s, favorite_car_id = %s WHERE id = %s',
              (bio, favorite_car_id, user_id))
    conn.commit()
    c.close()
    conn.close()


def update_avatar(user_id, avatar_data, avatar_mime):
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE users SET avatar_data = %s, avatar_mime = %s WHERE id = %s',
              (psycopg2.Binary(avatar_data), avatar_mime, user_id))
    conn.commit()
    c.close()
    conn.close()


def get_user_avatar(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT avatar_data, avatar_mime FROM users WHERE id = %s', (user_id,))
    row = c.fetchone()
    c.close()
    conn.close()
    return row


# ---------- БАЛАНС ----------
def get_balance(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT balance FROM users WHERE id = %s', (user_id,))
    row = c.fetchone()
    c.close()
    conn.close()
    return row[0] if row and row[0] is not None else 0


def add_coins(user_id, amount):
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE id = %s',
              (amount, user_id))
    conn.commit()
    c.close()
    conn.close()


# ---------- ЖУРНАЛ ----------
def log_transaction(user_id, ttype, amount, car_id, description):
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO transactions (user_id, type, amount, car_id, description, created_at)
                 VALUES (%s, %s, %s, %s, %s, %s)''',
              (user_id, ttype, amount, car_id, description, datetime.now().isoformat()))
    conn.commit()
    c.close()
    conn.close()


def get_user_transactions(user_id, limit=100):
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT id, type, amount, car_id, description, created_at
                 FROM transactions WHERE user_id = %s
                 ORDER BY id DESC LIMIT %s''', (user_id, limit))
    rows = c.fetchall()
    c.close()
    conn.close()
    return rows


# ---------- БОНУС ----------
def can_claim_bonus(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT last_bonus_at FROM users WHERE id = %s', (user_id,))
    row = c.fetchone()
    c.close()
    conn.close()
    if not row or not row[0]:
        return True, 0
    try:
        last = datetime.fromisoformat(row[0])
    except (ValueError, TypeError):
        return True, 0
    diff = (datetime.now() - last).total_seconds()
    if diff >= BONUS_COOLDOWN:
        return True, 0
    return False, int(BONUS_COOLDOWN - diff)


def claim_bonus(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE users SET balance = COALESCE(balance, 0) + %s, last_bonus_at = %s '
              'WHERE id = %s', (DAILY_BONUS, datetime.now().isoformat(), user_id))
    conn.commit()
    c.close()
    conn.close()
    log_transaction(user_id, 'bonus', DAILY_BONUS, None, 'Ежедневный бонус')


def format_time_left(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours} ч {minutes} мин"
    return f"{minutes} мин"


# ---------- КАТАЛОГ ----------
def get_catalog():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, model, rating, price FROM cars ORDER BY id DESC')
    rows = c.fetchall()
    c.close()
    conn.close()
    return rows


def get_catalog_by_rating(min_r, max_r):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, model, rating, price FROM cars '
              'WHERE rating BETWEEN %s AND %s ORDER BY id DESC', (min_r, max_r))
    rows = c.fetchall()
    c.close()
    conn.close()
    return rows


def add_car(model, rating, price, image_data, image_mime):
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO cars (model, rating, price, image_data, image_mime, created_at) '
              'VALUES (%s, %s, %s, %s, %s, %s)',
              (model, rating, price, psycopg2.Binary(image_data), image_mime,
               datetime.now().isoformat()))
    conn.commit()
    c.close()
    conn.close()


def update_car(car_id, model, rating, price):
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE cars SET model = %s, rating = %s, price = %s WHERE id = %s',
              (model, rating, price, car_id))
    conn.commit()
    c.close()
    conn.close()


def get_car_image(car_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT image_data, image_mime FROM cars WHERE id = %s', (car_id,))
    row = c.fetchone()
    c.close()
    conn.close()
    return row


def get_car_info(car_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, model, rating, price FROM cars WHERE id = %s', (car_id,))
    row = c.fetchone()
    c.close()
    conn.close()
    return row


def delete_car_from_catalog(car_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM user_cars WHERE car_id = %s', (car_id,))
    c.execute('DELETE FROM public_cars WHERE car_id = %s', (car_id,))
    c.execute('UPDATE users SET favorite_car_id = NULL WHERE favorite_car_id = %s', (car_id,))
    c.execute('DELETE FROM daily_discount WHERE car_id = %s', (car_id,))
    c.execute('DELETE FROM cars WHERE id = %s', (car_id,))
    conn.commit()
    c.close()
    conn.close()


# ---------- ЛИЧНЫЙ ГАРАЖ ----------
def get_user_cars(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT c.id, c.model, c.rating, c.price FROM cars c
                 JOIN user_cars uc ON uc.car_id = c.id
                 WHERE uc.user_id = %s ORDER BY uc.id DESC''', (user_id,))
    rows = c.fetchall()
    c.close()
    conn.close()
    return rows


def count_user_cars(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM user_cars WHERE user_id = %s', (user_id,))
    row = c.fetchone()
    c.close()
    conn.close()
    return row[0] if row else 0


def has_car(user_id, car_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT 1 FROM user_cars WHERE user_id = %s AND car_id = %s', (user_id, car_id))
    row = c.fetchone()
    c.close()
    conn.close()
    return row is not None


def buy_car(user_id, car_id):
    if has_car(user_id, car_id):
        return False, 'Эта машина уже в твоём гараже'
    car = get_car_info(car_id)
    if not car:
        return False, 'Машина не найдена'

    # Учитываем скидку дня
    discount = get_active_discount()
    final_price = car[3] or 0
    was_discounted = False
    if discount and discount['car_id'] == car_id:
        final_price = int(final_price * (100 - discount['discount_percent']) / 100)
        was_discounted = True

    balance = get_balance(user_id)
    if balance < final_price:
        return False, f'Не хватает монет. Нужно {final_price}, у тебя {balance}'

    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE users SET balance = COALESCE(balance, 0) - %s WHERE id = %s',
              (final_price, user_id))
    c.execute('INSERT INTO user_cars (user_id, car_id, opened_at) VALUES (%s, %s, %s)',
              (user_id, car_id, datetime.now().isoformat()))
    conn.commit()
    c.close()
    conn.close()

    desc = f'Покупка: {car[1]}' + (' (со скидкой дня)' if was_discounted else '')
    log_transaction(user_id, 'buy', -final_price, car_id, desc)
    return True, f'Куплена «{car[1]}» за {final_price} монет!'


def sell_car(user_id, car_id):
    if not has_car(user_id, car_id):
        return False, 'У тебя нет этой машины', 0
    car = get_car_info(car_id)
    if not car:
        return False, 'Машина не найдена', 0
    price = car[3] or 0
    refund = int(price * SELL_RATE)

    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM user_cars WHERE user_id = %s AND car_id = %s', (user_id, car_id))
    c.execute('DELETE FROM public_cars WHERE user_id = %s AND car_id = %s', (user_id, car_id))
    c.execute('UPDATE users SET favorite_car_id = NULL WHERE id = %s AND favorite_car_id = %s',
              (user_id, car_id))
    c.execute('UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE id = %s',
              (refund, user_id))
    conn.commit()
    c.close()
    conn.close()

    log_transaction(user_id, 'sell', refund, car_id, f'Продажа: {car[1]}')
    return True, f'«{car[1]}» продана за {refund} монет', refund


# ---------- СКИДКА ДНЯ ----------
def get_active_discount():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, car_id, discount_percent, set_at, expires_at FROM daily_discount '
              'ORDER BY id DESC LIMIT 1')
    row = c.fetchone()
    c.close()
    conn.close()
    if not row:
        return None
    try:
        expires = datetime.fromisoformat(row[4])
    except (ValueError, TypeError):
        return None
    if expires <= datetime.now():
        return None
    return {'id': row[0], 'car_id': row[1], 'discount_percent': row[2]}


def roll_new_discount():
    """Создаёт новую скидку дня, если возможно."""
    if get_setting('discount_enabled') != '1':
        return None
    min_r = get_int_setting('discount_min_rating', 1)
    max_r = get_int_setting('discount_max_rating', 3)
    percent = get_int_setting('discount_percent', 50)
    candidates = get_catalog_by_rating(min_r, max_r)
    if not candidates:
        return None
    chosen = random.choice(candidates)
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM daily_discount')  # чистим старые
    c.execute('INSERT INTO daily_discount (car_id, discount_percent, set_at, expires_at) '
              'VALUES (%s, %s, %s, %s)',
              (chosen[0], percent, datetime.now().isoformat(),
               (datetime.now() + timedelta(hours=24)).isoformat()))
    conn.commit()
    c.close()
    conn.close()
    return {'car_id': chosen[0], 'model': chosen[1], 'discount_percent': percent}


def ensure_discount():
    """Проверяет и создаёт скидку, если нужно. Вызывается при заходе в магазин."""
    if get_active_discount() is None:
        return roll_new_discount()
    return None


# ---------- КОЛЕСО ФОРТУНЫ ----------
def can_spin(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT last_spin_at FROM users WHERE id = %s', (user_id,))
    row = c.fetchone()
    c.close()
    conn.close()
    cooldown_hours = get_int_setting('wheel_cooldown_hours', 24)
    cooldown_secs = cooldown_hours * 3600
    if not row or not row[0]:
        return True, 0
    try:
        last = datetime.fromisoformat(row[0])
    except (ValueError, TypeError):
        return True, 0
    diff = (datetime.now() - last).total_seconds()
    if diff >= cooldown_secs:
        return True, 0
    return False, int(cooldown_secs - diff)


def do_spin(user_id):
    """Крутит колесо и возвращает результат."""
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE users SET last_spin_at = %s WHERE id = %s',
              (datetime.now().isoformat(), user_id))
    conn.commit()
    c.close()
    conn.close()

    car_chance = get_int_setting('wheel_car_chance', 10)
    coin_min = get_int_setting('wheel_coin_min', 50)
    coin_max = get_int_setting('wheel_coin_max', 500)

    roll = random.randint(1, 100)
    if roll <= car_chance:
        # Выпала машина
        min_r = get_int_setting('wheel_car_min_rating', 1)
        max_r = get_int_setting('wheel_car_max_rating', 5)
        candidates = [car for car in get_catalog_by_rating(min_r, max_r)
                      if not has_car(user_id, car[0])]
        if candidates:
            chosen = random.choice(candidates)
            conn = get_db()
            c = conn.cursor()
            c.execute('INSERT INTO user_cars (user_id, car_id, opened_at) VALUES (%s, %s, %s)',
                      (user_id, chosen[0], datetime.now().isoformat()))
            conn.commit()
            c.close()
            conn.close()
            log_transaction(user_id, 'wheel_car', 0, chosen[0],
                            f'Колесо фортуны: {chosen[1]}')
            return {'type': 'car', 'car_id': chosen[0], 'model': chosen[1], 'rating': chosen[2]}
        # Если все машины уже есть — выдаём монеты
    # Монеты
    amount = random.randint(coin_min, coin_max)
    add_coins(user_id, amount)
    log_transaction(user_id, 'wheel_coins', amount, None, 'Колесо фортуны: монеты')
    return {'type': 'coins', 'amount': amount}


# ---------- ХЕЛПЕРЫ ----------
def is_admin(username):
    return username in ADMIN_USERNAMES


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Сначала войди в аккаунт')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Сначала войди в аккаунт')
            return redirect(url_for('login'))
        if not is_admin(session.get('username')):
            flash('Доступ только для администратора')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated


ALLOWED_MIME = {'image/png', 'image/jpeg', 'image/webp', 'image/gif'}


# ---------- МАРШРУТЫ ----------
@app.route('/')
def index():
    profile = None
    favorite_car = None
    cars_count = 0
    bonus_ready = False
    bonus_left = ''
    spin_ready = False
    spin_left = ''
    if 'user_id' in session:
        profile = get_user_profile(session['user_id'])
        if profile and profile['favorite_car_id']:
            favorite_car = get_car_info(profile['favorite_car_id'])
        cars_count = count_user_cars(session['user_id'])
        bonus_ready, secs = can_claim_bonus(session['user_id'])
        if not bonus_ready:
            bonus_left = format_time_left(secs)
        spin_ready, secs2 = can_spin(session['user_id'])
        if not spin_ready:
            spin_left = format_time_left(secs2)
    return render_template('index.html',
                           user=session.get('username'), profile=profile,
                           favorite_car=favorite_car, cars_count=cars_count,
                           bonus_ready=bonus_ready, bonus_left=bonus_left,
                           spin_ready=spin_ready, spin_left=spin_left,
                           is_admin=is_admin(session.get('username')))


@app.route('/bonus', methods=['POST'])
@login_required
def bonus():
    ready, _ = can_claim_bonus(session['user_id'])
    if ready:
        claim_bonus(session['user_id'])
        flash(f'🎁 Ежедневный бонус получен: +{DAILY_BONUS} монет!')
    else:
        flash('Бонус пока недоступен')
    return redirect(url_for('index'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        password2 = request.form.get('password2', '')
        if not username or not password:
            flash('Заполни все поля'); return redirect(url_for('register'))
        if len(username) < 3 or len(username) > 20:
            flash('Никнейм от 3 до 20 символов'); return redirect(url_for('register'))
        if len(password) < 6:
            flash('Пароль минимум 6 символов'); return redirect(url_for('register'))
        if password != password2:
            flash('Пароли не совпадают'); return redirect(url_for('register'))
        if get_user(username):
            flash('Такой никнейм уже занят'); return redirect(url_for('register'))
        create_user(username, password)
        user = get_user(username)
        session['user_id'] = user[0]
        session['username'] = user[1]
        flash(f'Добро пожаловать! Тебе начислено {START_BALANCE} монет')
        return redirect(url_for('index'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = get_user(username)
        if user and check_password_hash(user[2], password):
            session['user_id'] = user[0]
            session['username'] = user[1]
            return redirect(url_for('index'))
        flash('Неверный никнейм или пароль')
        return redirect(url_for('login'))
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    return redirect(url_for('index'))


# ---------- ПРОФИЛЬ ----------
@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    user_id = session['user_id']
    if request.method == 'POST':
        bio = request.form.get('bio', '').strip()[:200]
        fav = request.form.get('favorite_car_id', '').strip()
        favorite_car_id = None
        if fav and fav.isdigit():
            car_id = int(fav)
            if has_car(user_id, car_id):
                favorite_car_id = car_id
        file = request.files.get('avatar')
        if file and file.filename != '':
            if file.mimetype in ALLOWED_MIME:
                update_avatar(user_id, file.read(), file.mimetype)
            else:
                flash('Аватарка: разрешены PNG, JPG, WEBP, GIF')
                return redirect(url_for('settings'))
        public_ids = request.form.getlist('public_cars')
        public_ids = [int(x) for x in public_ids if x.isdigit()]
        my_ids = {car[0] for car in get_user_cars(user_id)}
        public_ids = [x for x in public_ids if x in my_ids]
        set_public_cars(user_id, public_ids)
        update_profile(user_id, bio, favorite_car_id)
        flash('Профиль обновлён!')
        return redirect(url_for('index'))
    profile = get_user_profile(user_id)
    my_cars = get_user_cars(user_id)
    public_ids = get_public_ids(user_id)
    return render_template('settings.html', user=session.get('username'), profile=profile,
                           my_cars=my_cars, public_ids=public_ids,
                           is_admin=is_admin(session.get('username')))


@app.route('/avatar/<int:user_id>')
def avatar(user_id):
    row = get_user_avatar(user_id)
    if not row or not row[0]:
        return '', 404
    image_data, mime = row
    return Response(bytes(image_data), mimetype=mime or 'image/png')


@app.route('/profile/<username>')
def profile_page(username):
    user_row = get_user(username)
    if not user_row:
        flash('Такого игрока нет'); return redirect(url_for('index'))
    profile = get_user_profile(user_row[0])
    favorite_car = None
    if profile['favorite_car_id']:
        favorite_car = get_car_info(profile['favorite_car_id'])
    public_cars = get_public_cars(user_row[0])
    cars_count = count_user_cars(user_row[0])
    return render_template('profile.html', profile=profile, favorite_car=favorite_car,
                           public_cars=public_cars, cars_count=cars_count,
                           user=session.get('username'),
                           is_admin=is_admin(session.get('username')))


# ---------- ГАРАЖ ----------
@app.route('/garage')
@login_required
def garage():
    cars = get_user_cars(session['user_id'])
    balance = get_balance(session['user_id'])
    return render_template('garage.html', cars=cars, balance=balance,
                           user=session.get('username'),
                           is_admin=is_admin(session.get('username')))


@app.route('/garage/remove/<int:car_id>', methods=['POST'])
@login_required
def remove_from_garage(car_id):
    success, msg, _ = sell_car(session['user_id'], car_id)
    flash(msg)
    return redirect(url_for('garage'))


# ---------- МАГАЗИН ----------
@app.route('/shop')
@login_required
def shop():
    ensure_discount()
    discount = get_active_discount()
    cars = get_catalog()
    balance = get_balance(session['user_id'])
    cars_with_status = []
    for car in cars:
        car_id, model, rating, price = car
        price = price or 0
        final_price = price
        has_disc = False
        if discount and discount['car_id'] == car_id:
            final_price = int(price * (100 - discount['discount_percent']) / 100)
            has_disc = True
        cars_with_status.append({
            'id': car_id, 'model': model, 'rating': rating,
            'price': price, 'final_price': final_price, 'has_discount': has_disc,
            'owned': has_car(session['user_id'], car_id),
        })
    return render_template('shop.html', cars=cars_with_status, balance=balance,
                           discount=discount,
                           user=session.get('username'),
                           is_admin=is_admin(session.get('username')))


@app.route('/shop/buy/<int:car_id>', methods=['POST'])
@login_required
def shop_buy(car_id):
    success, msg = buy_car(session['user_id'], car_id)
    flash(msg)
    return redirect(url_for('shop'))


@app.route('/shop/add', methods=['GET', 'POST'])
@admin_required
def add_car_page():
    if request.method == 'POST':
        model = request.form.get('model', '').strip()
        rating = request.form.get('rating', '3')
        price = request.form.get('price', '500')
        file = request.files.get('image')
        if not model:
            flash('Впиши название'); return redirect(url_for('add_car_page'))
        try:
            rating = int(rating)
            if rating < 1 or rating > 8: raise ValueError
        except ValueError:
            flash('Оценка от 1 до 8'); return redirect(url_for('add_car_page'))
        try:
            price = int(price)
            if price < 0: raise ValueError
        except ValueError:
            flash('Цена — неотрицательное число'); return redirect(url_for('add_car_page'))
        if not file or file.filename == '':
            flash('Выбери картинку'); return redirect(url_for('add_car_page'))
        if file.mimetype not in ALLOWED_MIME:
            flash('Только PNG, JPG, WEBP, GIF'); return redirect(url_for('add_car_page'))
        add_car(model, rating, price, file.read(), file.mimetype)
        flash(f'Машина «{model}» добавлена!')
        return redirect(url_for('shop'))
    return render_template('add_car.html', user=session.get('username'), is_admin=True)


@app.route('/shop/edit/<int:car_id>', methods=['GET', 'POST'])
@admin_required
def edit_car_page(car_id):
    car = get_car_info(car_id)
    if not car:
        flash('Машина не найдена'); return redirect(url_for('shop'))
    if request.method == 'POST':
        model = request.form.get('model', '').strip()
        rating = request.form.get('rating', '3')
        price = request.form.get('price', '500')
        if not model:
            flash('Впиши название'); return redirect(url_for('edit_car_page', car_id=car_id))
        try:
            rating = int(rating)
            if rating < 1 or rating > 8: raise ValueError
        except ValueError:
            flash('Оценка от 1 до 8'); return redirect(url_for('edit_car_page', car_id=car_id))
        try:
            price = int(price)
            if price < 0: raise ValueError
        except ValueError:
            flash('Цена — неотрицательное число'); return redirect(url_for('edit_car_page', car_id=car_id))
        update_car(car_id, model, rating, price)
        flash('Машина обновлена')
        return redirect(url_for('shop'))
    return render_template('edit_car.html', car=car, user=session.get('username'), is_admin=True)


@app.route('/shop/delete/<int:car_id>', methods=['POST'])
@admin_required
def delete_from_catalog(car_id):
    delete_car_from_catalog(car_id)
    flash('Машина удалена')
    return redirect(url_for('shop'))


# ---------- КОЛЕСО ФОРТУНЫ ----------
@app.route('/wheel')
@login_required
def wheel():
    ready, secs = can_spin(session['user_id'])
    balance = get_balance(session['user_id'])
    result = session.pop('wheel_result', None)
    return render_template('wheel.html',
                           ready=ready,
                           time_left=format_time_left(secs) if not ready else '',
                           result=result,
                           balance=balance,
                           user=session.get('username'),
                           is_admin=is_admin(session.get('username')))


@app.route('/wheel/spin', methods=['POST'])
@login_required
def wheel_spin():
    ready, _ = can_spin(session['user_id'])
    if not ready:
        flash('Колесо пока недоступно')
        return redirect(url_for('wheel'))
    result = do_spin(session['user_id'])
    session['wheel_result'] = result
    return redirect(url_for('wheel'))


# ---------- ЖУРНАЛ ----------
@app.route('/journal')
@login_required
def journal():
    txs = get_user_transactions(session['user_id'], limit=200)
    balance = get_balance(session['user_id'])
    return render_template('journal.html', transactions=txs, balance=balance,
                           user=session.get('username'),
                           is_admin=is_admin(session.get('username')))


# ---------- АДМИН-НАСТРОЙКИ ----------
@app.route('/admin/settings', methods=['GET', 'POST'])
@admin_required
def admin_settings():
    if request.method == 'POST':
        # Скидка дня
        set_setting('discount_enabled', '1' if request.form.get('discount_enabled') else '0')
        set_setting('discount_min_rating', request.form.get('discount_min_rating', '1'))
        set_setting('discount_max_rating', request.form.get('discount_max_rating', '3'))
        set_setting('discount_percent', request.form.get('discount_percent', '50'))
        # Колесо
        set_setting('wheel_enabled', '1' if request.form.get('wheel_enabled') else '0')
        set_setting('wheel_coin_min', request.form.get('wheel_coin_min', '50'))
        set_setting('wheel_coin_max', request.form.get('wheel_coin_max', '500'))
        set_setting('wheel_car_chance', request.form.get('wheel_car_chance', '10'))
        set_setting('wheel_car_min_rating', request.form.get('wheel_car_min_rating', '1'))
        set_setting('wheel_car_max_rating', request.form.get('wheel_car_max_rating', '5'))
        set_setting('wheel_cooldown_hours', request.form.get('wheel_cooldown_hours', '24'))
        flash('Настройки сохранены!')
        return redirect(url_for('admin_settings'))

    settings = {k: get_setting(k) for k in DEFAULT_SETTINGS}
    discount = get_active_discount()
    discount_car = None
    if discount:
        discount_car = get_car_info(discount['car_id'])
    return render_template('admin_settings.html', settings=settings,
                           discount=discount, discount_car=discount_car,
                           user=session.get('username'), is_admin=True)


@app.route('/admin/discount/reroll', methods=['POST'])
@admin_required
def admin_reroll_discount():
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM daily_discount')
    conn.commit()
    c.close()
    conn.close()
    result = roll_new_discount()
    if result:
        flash(f'Новая скидка дня: «{result["model"]}» — {result["discount_percent"]}%')
    else:
        flash('Не удалось выбрать машину. Проверь диапазон рейтинга.')
    return redirect(url_for('admin_settings'))


# ---------- КАРТИНКИ ----------
@app.route('/car_image/<int:car_id>')
def car_image(car_id):
    row = get_car_image(car_id)
    if not row:
        return '', 404
    image_data, mime = row
    return Response(bytes(image_data), mimetype=mime)


init_db()

if __name__ == '__main__':
    app.run(debug=True)

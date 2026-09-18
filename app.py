from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash, Response)
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import psycopg2
import psycopg2.extras
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-me-please')

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    raise RuntimeError('Не найдена переменная DATABASE_URL.')

DATABASE_URL = DATABASE_URL.replace('?sslmode=require', '').replace('&sslmode=require', '')

app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024

# ============ ЭКОНОМИКА ============
START_BALANCE = 500        # сколько монет при регистрации
DAILY_BONUS = 100          # ежедневный бонус
SELL_RATE = 0.7            # 70% от цены при продаже
BONUS_COOLDOWN = 86400     # 24 часа в секундах

# ============ КТО АДМИН ============
ADMIN_USERNAMES = {'AppleAT'}


# ---------- ПОДКЛЮЧЕНИЕ К БАЗЕ ----------
def get_db():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(20) UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    ''')
    c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_data BYTEA')
    c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_mime TEXT')
    c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS bio TEXT')
    c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS favorite_car_id INTEGER')
    c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS balance INTEGER')
    c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS last_bonus_at TEXT')

    c.execute('''
        CREATE TABLE IF NOT EXISTS cars (
            id SERIAL PRIMARY KEY,
            model VARCHAR(60) NOT NULL,
            rating INTEGER NOT NULL,
            image_data BYTEA NOT NULL,
            image_mime TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    ''')
    c.execute('ALTER TABLE cars ADD COLUMN IF NOT EXISTS price INTEGER')
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_cars (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            car_id INTEGER NOT NULL,
            opened_at TEXT NOT NULL,
            UNIQUE(user_id, car_id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS public_cars (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            car_id INTEGER NOT NULL,
            UNIQUE(user_id, car_id)
        )
    ''')

    # Миграция: у старых пользователей / машин без баланса и цены — ставим дефолт
    c.execute('UPDATE users SET balance = %s WHERE balance IS NULL', (START_BALANCE,))
    c.execute('UPDATE cars SET price = 500 WHERE price IS NULL')

    conn.commit()
    c.close()
    conn.close()


# ---------- Пользователи ----------
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
              (username, generate_password_hash(password), datetime.now().isoformat(), START_BALANCE))
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
        'id': row[0],
        'username': row[1],
        'avatar_data': row[2],
        'avatar_mime': row[3],
        'bio': row[4],
        'favorite_car_id': row[5],
        'balance': row[6] or 0,
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


# ---------- Баланс и бонус ----------
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


def can_claim_bonus(user_id):
    """Возвращает (можно_ли_получить, осталось_секунд)."""
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
              'WHERE id = %s',
              (DAILY_BONUS, datetime.now().isoformat(), user_id))
    conn.commit()
    c.close()
    conn.close()


def format_time_left(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours} ч {minutes} мин"
    return f"{minutes} мин"


# ---------- Каталог / магазин ----------
def get_catalog():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, model, rating, price FROM cars ORDER BY id DESC')
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
    c.execute('DELETE FROM cars WHERE id = %s', (car_id,))
    conn.commit()
    c.close()
    conn.close()


# ---------- Личный гараж ----------
def get_user_cars(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT c.id, c.model, c.rating, c.price
        FROM cars c
        JOIN user_cars uc ON uc.car_id = c.id
        WHERE uc.user_id = %s
        ORDER BY uc.id DESC
    ''', (user_id,))
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
    """Покупает машину, если хватает монет и её ещё нет в гараже.
    Возвращает (успех, сообщение)."""
    if has_car(user_id, car_id):
        return False, 'Эта машина уже в твоём гараже'

    car = get_car_info(car_id)
    if not car:
        return False, 'Машина не найдена'
    price = car[3] or 0
    balance = get_balance(user_id)
    if balance < price:
        return False, f'Не хватает монет. Нужно {price}, у тебя {balance}'

    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE users SET balance = COALESCE(balance, 0) - %s WHERE id = %s',
              (price, user_id))
    c.execute('INSERT INTO user_cars (user_id, car_id, opened_at) VALUES (%s, %s, %s)',
              (user_id, car_id, datetime.now().isoformat()))
    conn.commit()
    c.close()
    conn.close()
    return True, f'Куплена «{car[1]}» за {price} монет!'


def sell_car(user_id, car_id):
    """Продаёт машину за SELL_RATE от цены. Возвращает (успех, сообщение, сумма)."""
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
    c.execute('UPDATE users SET favorite_car_id = NULL '
              'WHERE id = %s AND favorite_car_id = %s', (user_id, car_id))
    c.execute('UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE id = %s',
              (refund, user_id))
    conn.commit()
    c.close()
    conn.close()
    return True, f'«{car[1]}» продана за {refund} монет', refund


# ---------- Публичный гараж ----------
def get_public_cars(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT c.id, c.model, c.rating, c.price
        FROM cars c
        JOIN public_cars pc ON pc.car_id = c.id
        WHERE pc.user_id = %s
        ORDER BY pc.id DESC
    ''', (user_id,))
    rows = c.fetchall()
    c.close()
    conn.close()
    return rows


def get_public_ids(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT car_id FROM public_cars WHERE user_id = %s', (user_id,))
    rows = c.fetchall()
    c.close()
    conn.close()
    return {r[0] for r in rows}


def set_public_cars(user_id, car_ids):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM public_cars WHERE user_id = %s', (user_id,))
    for car_id in car_ids:
        c.execute('INSERT INTO public_cars (user_id, car_id) VALUES (%s, %s) '
                  'ON CONFLICT (user_id, car_id) DO NOTHING', (user_id, car_id))
    conn.commit()
    c.close()
    conn.close()


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
    bonus_left_str = ''
    if 'user_id' in session:
        profile = get_user_profile(session['user_id'])
        if profile and profile['favorite_car_id']:
            favorite_car = get_car_info(profile['favorite_car_id'])
        cars_count = count_user_cars(session['user_id'])
        bonus_ready, secs = can_claim_bonus(session['user_id'])
        if not bonus_ready:
            bonus_left_str = format_time_left(secs)
    return render_template('index.html',
                           user=session.get('username'),
                           profile=profile,
                           favorite_car=favorite_car,
                           cars_count=cars_count,
                           bonus_ready=bonus_ready,
                           bonus_left=bonus_left_str,
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
            flash('Заполни все поля')
            return redirect(url_for('register'))
        if len(username) < 3 or len(username) > 20:
            flash('Никнейм должен быть от 3 до 20 символов')
            return redirect(url_for('register'))
        if len(password) < 6:
            flash('Пароль должен быть не короче 6 символов')
            return redirect(url_for('register'))
        if password != password2:
            flash('Пароли не совпадают')
            return redirect(url_for('register'))
        if get_user(username):
            flash('Такой никнейм уже занят')
            return redirect(url_for('register'))

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
    return render_template('settings.html',
                           user=session.get('username'),
                           profile=profile,
                           my_cars=my_cars,
                           public_ids=public_ids,
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
        flash('Такого игрока нет')
        return redirect(url_for('index'))
    profile = get_user_profile(user_row[0])
    favorite_car = None
    if profile['favorite_car_id']:
        favorite_car = get_car_info(profile['favorite_car_id'])
    public_cars = get_public_cars(user_row[0])
    cars_count = count_user_cars(user_row[0])
    return render_template('profile.html',
                           profile=profile,
                           favorite_car=favorite_car,
                           public_cars=public_cars,
                           cars_count=cars_count,
                           user=session.get('username'),
                           is_admin=is_admin(session.get('username')))


# ---------- ЛИЧНЫЙ ГАРАЖ ----------
@app.route('/garage')
@login_required
def garage():
    cars = get_user_cars(session['user_id'])
    balance = get_balance(session['user_id'])
    return render_template('garage.html',
                           cars=cars,
                           balance=balance,
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
    cars = get_catalog()
    balance = get_balance(session['user_id'])
    cars_with_status = []
    for car in cars:
        car_id, model, rating, price = car
        cars_with_status.append({
            'id': car_id,
            'model': model,
            'rating': rating,
            'price': price or 0,
            'owned': has_car(session['user_id'], car_id),
        })
    return render_template('shop.html',
                           cars=cars_with_status,
                           balance=balance,
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
            flash('Впиши название модели')
            return redirect(url_for('add_car_page'))
        try:
            rating = int(rating)
            if rating < 1 or rating > 8:
                raise ValueError
        except ValueError:
            flash('Оценка должна быть от 1 до 8')
            return redirect(url_for('add_car_page'))
        try:
            price = int(price)
            if price < 0:
                raise ValueError
        except ValueError:
            flash('Цена должна быть неотрицательным числом')
            return redirect(url_for('add_car_page'))
        if not file or file.filename == '':
            flash('Выбери картинку')
            return redirect(url_for('add_car_page'))
        if file.mimetype not in ALLOWED_MIME:
            flash('Разрешены только PNG, JPG, WEBP, GIF')
            return redirect(url_for('add_car_page'))

        image_data = file.read()
        add_car(model, rating, price, image_data, file.mimetype)
        flash(f'Машина «{model}» добавлена в магазин!')
        return redirect(url_for('shop'))

    return render_template('add_car.html',
                           user=session.get('username'),
                           is_admin=True)


@app.route('/shop/edit/<int:car_id>', methods=['GET', 'POST'])
@admin_required
def edit_car_page(car_id):
    car = get_car_info(car_id)
    if not car:
        flash('Машина не найдена')
        return redirect(url_for('shop'))

    if request.method == 'POST':
        model = request.form.get('model', '').strip()
        rating = request.form.get('rating', '3')
        price = request.form.get('price', '500')

        if not model:
            flash('Впиши название модели')
            return redirect(url_for('edit_car_page', car_id=car_id))
        try:
            rating = int(rating)
            if rating < 1 or rating > 8:
                raise ValueError
        except ValueError:
            flash('Оценка должна быть от 1 до 8')
            return redirect(url_for('edit_car_page', car_id=car_id))
        try:
            price = int(price)
            if price < 0:
                raise ValueError
        except ValueError:
            flash('Цена должна быть неотрицательным числом')
            return redirect(url_for('edit_car_page', car_id=car_id))

        update_car(car_id, model, rating, price)
        flash('Машина обновлена')
        return redirect(url_for('shop'))

    return render_template('edit_car.html',
                           car=car,
                           user=session.get('username'),
                           is_admin=True)


@app.route('/shop/delete/<int:car_id>', methods=['POST'])
@admin_required
def delete_from_catalog(car_id):
    delete_car_from_catalog(car_id)
    flash('Машина удалена из магазина и из всех гаражей')
    return redirect(url_for('shop'))


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

from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash, Response)
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

ADMIN_USERNAMES = {'AppleAT'}

DEFAULT_SETTINGS = {
    'discount_enabled': '1',
    'discount_min_rating': '1',
    'discount_max_rating': '3',
    'discount_percent': '50',

    'wheel_enabled': '1',
    'wheel_coin_min': '50',
    'wheel_coin_max': '500',
    'wheel_car_chance': '10',
    'wheel_car_min_rating': '1',
    'wheel_car_max_rating': '5',
    'wheel_cooldown_hours': '24',

    'paid_wheel_enabled': '1',
    'paid_wheel_price': '300',
    'paid_wheel_coin_min': '200',
    'paid_wheel_coin_max': '2000',
    'paid_wheel_car_chance': '30',
    'paid_wheel_car_min_rating': '4',
    'paid_wheel_car_max_rating': '8',
}

# ============ ДОСТИЖЕНИЯ ============
ACHIEVEMENTS = [
    {'key': 'first_car',   'icon': '🚗', 'title': 'Первая ласточка',  'desc': 'Получить первую машину в гараж'},
    {'key': 'cars_5',      'icon': '🏎️', 'title': 'Коллекционер',     'desc': 'Собрать 5 машин'},
    {'key': 'cars_10',     'icon': '🏁', 'title': 'Автолюбитель',     'desc': 'Собрать 10 машин'},
    {'key': 'cars_25',     'icon': '🏛️', 'title': 'Автомузей',        'desc': 'Собрать 25 машин'},
    {'key': 'cars_50',     'icon': '👑', 'title': 'Мега-коллекция',   'desc': 'Собрать 50 машин'},
    {'key': 'rich_1000',   'icon': '💰', 'title': 'Богач',            'desc': 'Накопить 1000 монет'},
    {'key': 'rich_5000',   'icon': '💎', 'title': 'Миллионер',        'desc': 'Накопить 5000 монет'},
    {'key': 'rich_10000',  'icon': '🏦', 'title': 'Банкир',           'desc': 'Накопить 10 000 монет'},
    {'key': 'first_sell',  'icon': '💵', 'title': 'Первый обмен',     'desc': 'Продать первую машину'},
    {'key': 'bonus_3',     'icon': '🎁', 'title': 'Бонус-охотник',    'desc': 'Забрать бонус 3 раза'},
    {'key': 'bonus_7',     'icon': '📅', 'title': 'Верный игрок',     'desc': 'Забрать бонус 7 раз'},
    {'key': 'spin_5',      'icon': '🎡', 'title': 'Колесник',         'desc': 'Покрутить колесо 5 раз'},
    {'key': 'spin_20',     'icon': '🎰', 'title': 'Азартный',         'desc': 'Покрутить колесо 20 раз'},
    {'key': 'lucky_car',   'icon': '🍀', 'title': 'Счастливчик',      'desc': 'Выиграть машину в колесе'},
    {'key': 'five_star',   'icon': '⭐', 'title': 'Пятизвёздочный',   'desc': 'Владеть машиной с 5★ или выше'},
    {'key': 'eight_star',  'icon': '🌟', 'title': 'Легенда',          'desc': 'Владеть машиной с 8★'},
    {'key': 'premium',     'icon': '💎', 'title': 'VIP',              'desc': 'Крутить премиум-колесо'},
    {'key': 'big_spender', 'icon': '🤑', 'title': 'Транжира',         'desc': 'Купить 10 машин'},
]


# ---------- БАЗА ----------
def get_db():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY, username VARCHAR(20) UNIQUE NOT NULL,
        password_hash TEXT NOT NULL, created_at TEXT NOT NULL
    )''')
    c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_data BYTEA')
    c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_mime TEXT')
    c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS bio TEXT')
    c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS favorite_car_id INTEGER')
    c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS balance INTEGER')
    c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS last_bonus_at TEXT')
    c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS last_spin_at TEXT')

    c.execute('''CREATE TABLE IF NOT EXISTS cars (
        id SERIAL PRIMARY KEY, model VARCHAR(60) NOT NULL, rating INTEGER NOT NULL,
        image_data BYTEA NOT NULL, image_mime TEXT NOT NULL, created_at TEXT NOT NULL
    )''')
    c.execute('ALTER TABLE cars ADD COLUMN IF NOT EXISTS price INTEGER')
    c.execute('ALTER TABLE cars ADD COLUMN IF NOT EXISTS horsepower INTEGER')
    c.execute('ALTER TABLE cars ADD COLUMN IF NOT EXISTS acceleration REAL')
    c.execute('ALTER TABLE cars ADD COLUMN IF NOT EXISTS top_speed INTEGER')

    c.execute('''CREATE TABLE IF NOT EXISTS user_cars (
        id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, car_id INTEGER NOT NULL,
        opened_at TEXT NOT NULL, UNIQUE(user_id, car_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS public_cars (
        id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, car_id INTEGER NOT NULL,
        UNIQUE(user_id, car_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY, value TEXT NOT NULL
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS daily_discount (
        id SERIAL PRIMARY KEY, car_id INTEGER NOT NULL, discount_percent INTEGER NOT NULL,
        set_at TEXT NOT NULL, expires_at TEXT NOT NULL
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, type VARCHAR(30) NOT NULL,
        amount INTEGER NOT NULL DEFAULT 0, car_id INTEGER,
        description TEXT NOT NULL, created_at TEXT NOT NULL
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_achievements (
        id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, key TEXT NOT NULL,
        unlocked_at TEXT NOT NULL, UNIQUE(user_id, key)
    )''')
  
    c.execute('''CREATE TABLE IF NOT EXISTS trades (
        id SERIAL PRIMARY KEY,
        from_user_id INTEGER NOT NULL,
        to_user_id INTEGER NOT NULL,
        from_car_id INTEGER NOT NULL,
        from_coins INTEGER NOT NULL DEFAULT 0,
        to_car_id INTEGER,
        to_coins INTEGER NOT NULL DEFAULT 0,
        message TEXT,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        resolved_at TEXT
    )''')

    c.execute('UPDATE users SET balance = %s WHERE balance IS NULL', (START_BALANCE,))
    c.execute('UPDATE cars SET price = 500 WHERE price IS NULL')
    for k, v in DEFAULT_SETTINGS.items():
        c.execute('INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING', (k, v))
    conn.commit()
    c.close()
    conn.close()


# ---------- НАСТРОЙКИ ----------
def get_setting(key, default=None):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT value FROM settings WHERE key = %s', (key,))
    row = c.fetchone(); c.close(); conn.close()
    return row[0] if row else (default if default is not None else DEFAULT_SETTINGS.get(key))


def get_int_setting(key, default=0):
    try:
        return int(get_setting(key))
    except (ValueError, TypeError):
        return default


def set_setting(key, value):
    conn = get_db(); c = conn.cursor()
    c.execute('INSERT INTO settings (key, value) VALUES (%s, %s) '
              'ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value', (key, str(value)))
    conn.commit(); c.close(); conn.close()


# ---------- ПОЛЬЗОВАТЕЛИ ----------
def get_user(username):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT id, username, password_hash FROM users WHERE username = %s', (username,))
    row = c.fetchone(); c.close(); conn.close()
    return row


def create_user(username, password):
    conn = get_db(); c = conn.cursor()
    c.execute('INSERT INTO users (username, password_hash, created_at, balance) '
              'VALUES (%s, %s, %s, %s)',
              (username, generate_password_hash(password), datetime.now().isoformat(), START_BALANCE))
    conn.commit(); c.close(); conn.close()


def get_user_profile(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT id, username, avatar_data, avatar_mime, bio, favorite_car_id, balance
                 FROM users WHERE id = %s''', (user_id,))
    row = c.fetchone(); c.close(); conn.close()
    if not row: return None
    return {'id': row[0], 'username': row[1], 'avatar_data': row[2], 'avatar_mime': row[3],
            'bio': row[4], 'favorite_car_id': row[5], 'balance': row[6] or 0}


def update_profile(user_id, bio, fav):
    conn = get_db(); c = conn.cursor()
    c.execute('UPDATE users SET bio = %s, favorite_car_id = %s WHERE id = %s', (bio, fav, user_id))
    conn.commit(); c.close(); conn.close()


def update_avatar(user_id, data, mime):
    conn = get_db(); c = conn.cursor()
    c.execute('UPDATE users SET avatar_data = %s, avatar_mime = %s WHERE id = %s',
              (psycopg2.Binary(data), mime, user_id))
    conn.commit(); c.close(); conn.close()


def get_user_avatar(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT avatar_data, avatar_mime FROM users WHERE id = %s', (user_id,))
    row = c.fetchone(); c.close(); conn.close()
    return row


# ---------- БАЛАНС ----------
def get_balance(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT balance FROM users WHERE id = %s', (user_id,))
    row = c.fetchone(); c.close(); conn.close()
    return row[0] if row and row[0] is not None else 0


def add_coins(user_id, amount):
    conn = get_db(); c = conn.cursor()
    c.execute('UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE id = %s', (amount, user_id))
    conn.commit(); c.close(); conn.close()


# ---------- ЖУРНАЛ ----------
def log_transaction(user_id, ttype, amount, car_id, description):
    conn = get_db(); c = conn.cursor()
    c.execute('''INSERT INTO transactions (user_id, type, amount, car_id, description, created_at)
                 VALUES (%s, %s, %s, %s, %s, %s)''',
              (user_id, ttype, amount, car_id, description, datetime.now().isoformat()))
    conn.commit(); c.close(); conn.close()


def get_user_transactions(user_id, limit=200):
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT id, type, amount, car_id, description, created_at
                 FROM transactions WHERE user_id = %s ORDER BY id DESC LIMIT %s''', (user_id, limit))
    rows = c.fetchall(); c.close(); conn.close()
    return rows


def count_tx(user_id, ttype):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM transactions WHERE user_id = %s AND type = %s', (user_id, ttype))
    r = c.fetchone(); c.close(); conn.close()
    return r[0] if r else 0


def count_tx_like(user_id, pattern):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM transactions WHERE user_id = %s AND type LIKE %s', (user_id, pattern))
    r = c.fetchone(); c.close(); conn.close()
    return r[0] if r else 0


# ---------- ДОСТИЖЕНИЯ ----------
def get_unlocked_keys(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT key FROM user_achievements WHERE user_id = %s', (user_id,))
    rows = c.fetchall(); c.close(); conn.close()
    return {r[0] for r in rows}


def unlock_achievement(user_id, key):
    conn = get_db(); c = conn.cursor()
    c.execute('INSERT INTO user_achievements (user_id, key, unlocked_at) VALUES (%s, %s, %s) '
              'ON CONFLICT (user_id, key) DO NOTHING',
              (user_id, key, datetime.now().isoformat()))
    conn.commit(); c.close(); conn.close()


def check_achievements(user_id):
    """Проверяет все достижения. Возвращает список новых ключей."""
    already = get_unlocked_keys(user_id)
    new_ones = []

    cars_count = count_user_cars(user_id)
    balance = get_balance(user_id)
    sells = count_tx(user_id, 'sell')
    bonuses = count_tx(user_id, 'bonus')
    spins = count_tx_like(user_id, 'wheel_%')
    paid_spins = count_tx_like(user_id, 'paid_wheel_%')
    wheel_cars = count_tx(user_id, 'wheel_car') + count_tx(user_id, 'paid_wheel_car')
    buys = count_tx(user_id, 'buy')
    max_rating = get_max_car_rating(user_id)

    checks = {
        'first_car':   cars_count >= 1,
        'cars_5':      cars_count >= 5,
        'cars_10':     cars_count >= 10,
        'cars_25':     cars_count >= 25,
        'cars_50':     cars_count >= 50,
        'rich_1000':   balance >= 1000,
        'rich_5000':   balance >= 5000,
        'rich_10000':  balance >= 10000,
        'first_sell':  sells >= 1,
        'bonus_3':     bonuses >= 3,
        'bonus_7':     bonuses >= 7,
        'spin_5':      spins >= 5,
        'spin_20':     spins >= 20,
        'lucky_car':   wheel_cars >= 1,
        'five_star':   max_rating >= 5,
        'eight_star':  max_rating >= 8,
        'premium':     paid_spins >= 1,
        'big_spender': buys >= 10,
    }

    for key, cond in checks.items():
        if key not in already and cond:
            unlock_achievement(user_id, key)
            new_ones.append(key)
    return new_ones


def get_max_car_rating(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT MAX(c.rating) FROM cars c
                 JOIN user_cars uc ON uc.car_id = c.id WHERE uc.user_id = %s''', (user_id,))
    r = c.fetchone(); c.close(); conn.close()
    return r[0] if r and r[0] else 0

# ---------- ОБМЕНЫ ----------
def get_username_by_id(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT username FROM users WHERE id = %s', (user_id,))
    row = c.fetchone(); c.close(); conn.close()
    return row[0] if row else '???'


def create_trade(from_user_id, to_username, from_car_id, from_coins, message):
    to_user = get_user(to_username)
    if not to_user:
        return False, 'Игрок с таким ником не найден'
    to_user_id = to_user[0]
    if to_user_id == from_user_id:
        return False, 'Нельзя предложить обмен самому себе'
    if not has_car(from_user_id, from_car_id):
        return False, 'У тебя нет этой машины'
    if from_coins < 0:
        return False, 'Монеты не могут быть отрицательными'
    if get_balance(from_user_id) < from_coins:
        return False, f'Не хватает монет. У тебя {get_balance(from_user_id)}'
    message = (message or '')[:200]
    conn = get_db(); c = conn.cursor()
    c.execute('''INSERT INTO trades
                 (from_user_id, to_user_id, from_car_id, from_coins, message, status, created_at)
                 VALUES (%s, %s, %s, %s, %s, 'pending', %s) RETURNING id''',
              (from_user_id, to_user_id, from_car_id, from_coins, message,
               datetime.now().isoformat()))
    trade_id = c.fetchone()[0]
    conn.commit(); c.close(); conn.close()
    return True, trade_id


def get_trade(trade_id):
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT id, from_user_id, to_user_id, from_car_id, from_coins,
                        to_car_id, to_coins, message, status, created_at, resolved_at
                 FROM trades WHERE id = %s''', (trade_id,))
    row = c.fetchone(); c.close(); conn.close()
    if not row: return None
    return {'id': row[0], 'from_user_id': row[1], 'to_user_id': row[2],
            'from_car_id': row[3], 'from_coins': row[4] or 0,
            'to_car_id': row[5], 'to_coins': row[6] or 0,
            'message': row[7], 'status': row[8],
            'created_at': row[9], 'resolved_at': row[10]}


def get_trade_full(trade_id):
    t = get_trade(trade_id)
    if not t: return None
    t['from_username'] = get_username_by_id(t['from_user_id'])
    t['to_username'] = get_username_by_id(t['to_user_id'])
    t['from_car'] = get_car_info(t['from_car_id'])
    t['to_car'] = get_car_info(t['to_car_id']) if t['to_car_id'] else None
    return t


def get_incoming_trades(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT id FROM trades WHERE to_user_id = %s AND status = 'pending'
                 ORDER BY id DESC''', (user_id,))
    ids = [r[0] for r in c.fetchall()]; c.close(); conn.close()
    return [get_trade_full(i) for i in ids]


def get_outgoing_trades(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT id FROM trades WHERE from_user_id = %s
                 ORDER BY id DESC LIMIT 50''', (user_id,))
    ids = [r[0] for r in c.fetchall()]; c.close(); conn.close()
    return [get_trade_full(i) for i in ids]


def get_trade_history(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT id FROM trades
                 WHERE (from_user_id = %s OR to_user_id = %s)
                   AND status IN ('completed', 'rejected', 'cancelled')
                 ORDER BY id DESC LIMIT 50''', (user_id, user_id))
    ids = [r[0] for r in c.fetchall()]; c.close(); conn.close()
    return [get_trade_full(i) for i in ids]


def count_incoming_trades(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT COUNT(*) FROM trades WHERE to_user_id = %s AND status = 'pending' ''',
              (user_id,))
    r = c.fetchone(); c.close(); conn.close()
    return r[0] if r else 0


def accept_trade(trade_id, user_id, to_car_id, to_coins):
    """Принимает обмен. to_car_id может быть None (не даю машину)."""
    t = get_trade(trade_id)
    if not t: return False, 'Обмен не найден'
    if t['to_user_id'] != user_id: return False, 'Это не твой обмен'
    if t['status'] != 'pending': return False, 'Обмен уже обработан'
    if to_coins < 0: return False, 'Монеты не могут быть отрицательными'

    # Проверяем монеты обеих сторон
    if get_balance(user_id) < to_coins:
        return False, f'У тебя только {get_balance(user_id)} монет'
    if get_balance(t['from_user_id']) < t['from_coins']:
        return False, 'У отправителя не хватает монет'

    # Проверяем машину отправителя
    if not has_car(t['from_user_id'], t['from_car_id']):
        return False, 'У отправителя уже нет этой машины'

    # Проверяем, нет ли уже такой машины у получателя
    if has_car(user_id, t['from_car_id']):
        return False, 'У тебя уже есть эта машина — обмен не имеет смысла'

    # Если получатель даёт машину — тоже проверяем
    if to_car_id:
        if not has_car(user_id, to_car_id):
            return False, 'У тебя нет этой машины'
        if has_car(t['from_user_id'], to_car_id):
            return False, 'У отправителя уже есть эта машина — обмен не имеет смысла'

    conn = get_db(); c = conn.cursor()

    # Забираем машину отправителя (она переходит получателю)
    c.execute('DELETE FROM user_cars WHERE user_id = %s AND car_id = %s',
              (t['from_user_id'], t['from_car_id']))
    c.execute('''INSERT INTO user_cars (user_id, car_id, opened_at)
                 VALUES (%s, %s, %s) ON CONFLICT (user_id, car_id) DO NOTHING''',
              (user_id, t['from_car_id'], datetime.now().isoformat()))
    c.execute('DELETE FROM public_cars WHERE user_id = %s AND car_id = %s',
              (t['from_user_id'], t['from_car_id']))
    c.execute('UPDATE users SET favorite_car_id = NULL WHERE id = %s AND favorite_car_id = %s',
              (t['from_user_id'], t['from_car_id']))

    # Если получатель отдаёт машину — она переходит отправителю
    if to_car_id:
        c.execute('DELETE FROM user_cars WHERE user_id = %s AND car_id = %s', (user_id, to_car_id))
        c.execute('''INSERT INTO user_cars (user_id, car_id, opened_at)
                     VALUES (%s, %s, %s) ON CONFLICT (user_id, car_id) DO NOTHING''',
                  (t['from_user_id'], to_car_id, datetime.now().isoformat()))
        c.execute('DELETE FROM public_cars WHERE user_id = %s AND car_id = %s', (user_id, to_car_id))
        c.execute('UPDATE users SET favorite_car_id = NULL WHERE id = %s AND favorite_car_id = %s',
                  (user_id, to_car_id))

    # Переводим монеты (разница)
    diff = t['from_coins'] - to_coins
    if diff > 0:
        c.execute('UPDATE users SET balance = COALESCE(balance, 0) - %s WHERE id = %s',
                  (diff, t['from_user_id']))
        c.execute('UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE id = %s',
                  (diff, user_id))
    elif diff < 0:
        c.execute('UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE id = %s',
                  (-diff, t['from_user_id']))
        c.execute('UPDATE users SET balance = COALESCE(balance, 0) - %s WHERE id = %s',
                  (-diff, user_id))

    c.execute('''UPDATE trades SET to_car_id = %s, to_coins = %s,
                 status = 'completed', resolved_at = %s WHERE id = %s''',
              (to_car_id, to_coins, datetime.now().isoformat(), trade_id))
    conn.commit(); c.close(); conn.close()

    other_name = get_username_by_id(user_id)
    my_name = get_username_by_id(t['from_user_id'])
    log_transaction(t['from_user_id'], 'trade', -diff if diff > 0 else -diff if diff < 0 else 0,
                    t['from_car_id'], f'Обмен с {other_name}')
    log_transaction(user_id, 'trade', diff if diff > 0 else (abs(diff) if diff < 0 else 0),
                    to_car_id, f'Обмен с {my_name}')
    return True, 'Обмен выполнен!'

    conn = get_db(); c = conn.cursor()
    # Забираем машины у обоих
    c.execute('DELETE FROM user_cars WHERE user_id = %s AND car_id = %s',
              (t['from_user_id'], t['from_car_id']))
    c.execute('DELETE FROM user_cars WHERE user_id = %s AND car_id = %s', (user_id, to_car_id))
    # Отдаём друг другу
    c.execute('INSERT INTO user_cars (user_id, car_id, opened_at) VALUES (%s, %s, %s)',
              (user_id, t['from_car_id'], datetime.now().isoformat()))
    c.execute('INSERT INTO user_cars (user_id, car_id, opened_at) VALUES (%s, %s, %s)',
              (t['from_user_id'], to_car_id, datetime.now().isoformat()))
    # Чистим публичные галереи и любимые
    c.execute('''DELETE FROM public_cars WHERE (user_id = %s AND car_id = %s)
                 OR (user_id = %s AND car_id = %s)''',
              (t['from_user_id'], t['from_car_id'], user_id, to_car_id))
    c.execute('''UPDATE users SET favorite_car_id = NULL
                 WHERE (id = %s AND favorite_car_id = %s) OR (id = %s AND favorite_car_id = %s)''',
              (t['from_user_id'], t['from_car_id'], user_id, to_car_id))
    # Монеты: разница идёт от получателя отправителю (или наоборот)
    diff = t['from_coins'] - to_coins  # >0 — отправитель доплачивает, <0 — получатель доплачивает
    if diff > 0:
        c.execute('UPDATE users SET balance = COALESCE(balance, 0) - %s WHERE id = %s',
                  (diff, t['from_user_id']))
        c.execute('UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE id = %s',
                  (diff, user_id))
    elif diff < 0:
        c.execute('UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE id = %s',
                  (-diff, t['from_user_id']))
        c.execute('UPDATE users SET balance = COALESCE(balance, 0) - %s WHERE id = %s',
                  (-diff, user_id))
    c.execute('''UPDATE trades SET to_car_id = %s, to_coins = %s,
                 status = 'completed', resolved_at = %s WHERE id = %s''',
              (to_car_id, to_coins, datetime.now().isoformat(), trade_id))
    conn.commit(); c.close(); conn.close()

    other_name = get_username_by_id(user_id)
    my_name = get_username_by_id(t['from_user_id'])
    log_transaction(t['from_user_id'], 'trade', -diff if diff > 0 else -diff if diff < 0 else 0,
                    t['from_car_id'], f'Обмен с {other_name}')
    log_transaction(user_id, 'trade', diff if diff > 0 else (abs(diff) if diff < 0 else 0),
                    to_car_id, f'Обмен с {my_name}')
    return True, 'Обмен выполнен!'


def reject_trade(trade_id, user_id):
    t = get_trade(trade_id)
    if not t: return False, 'Не найден'
    if t['to_user_id'] != user_id: return False, 'Это не твой обмен'
    if t['status'] != 'pending': return False, 'Уже обработан'
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE trades SET status = 'rejected', resolved_at = %s WHERE id = %s",
              (datetime.now().isoformat(), trade_id))
    conn.commit(); c.close(); conn.close()
    return True, 'Обмен отклонён'


def cancel_trade(trade_id, user_id):
    t = get_trade(trade_id)
    if not t: return False, 'Не найден'
    if t['from_user_id'] != user_id: return False, 'Это не твой обмен'
    if t['status'] != 'pending': return False, 'Уже обработан'
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE trades SET status = 'cancelled', resolved_at = %s WHERE id = %s",
              (datetime.now().isoformat(), trade_id))
    conn.commit(); c.close(); conn.close()
    return True, 'Обмен отменён'


def get_achievements_for_user(user_id):
    unlocked = get_unlocked_keys(user_id)
    result = []
    for a in ACHIEVEMENTS:
        result.append({**a, 'unlocked': a['key'] in unlocked})
    return result


# ---------- БОНУС ----------
def can_claim_bonus(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT last_bonus_at FROM users WHERE id = %s', (user_id,))
    row = c.fetchone(); c.close(); conn.close()
    if not row or not row[0]: return True, 0
    try: last = datetime.fromisoformat(row[0])
    except: return True, 0
    diff = (datetime.now() - last).total_seconds()
    if diff >= BONUS_COOLDOWN: return True, 0
    return False, int(BONUS_COOLDOWN - diff)


def claim_bonus(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('UPDATE users SET balance = COALESCE(balance, 0) + %s, last_bonus_at = %s WHERE id = %s',
              (DAILY_BONUS, datetime.now().isoformat(), user_id))
    conn.commit(); c.close(); conn.close()
    log_transaction(user_id, 'bonus', DAILY_BONUS, None, 'Ежедневный бонус')


def format_time_left(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0: return f"{hours} ч {minutes} мин"
    return f"{minutes} мин"


# ---------- КАТАЛОГ ----------
def get_catalog():
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT id, model, rating, price FROM cars ORDER BY id DESC')
    rows = c.fetchall(); c.close(); conn.close()
    return rows


def get_catalog_by_rating(min_r, max_r):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT id, model, rating, price FROM cars WHERE rating BETWEEN %s AND %s ORDER BY id DESC',
              (min_r, max_r))
    rows = c.fetchall(); c.close(); conn.close()
    return rows


def add_car(model, rating, price, horsepower, acceleration, top_speed, data, mime):
    conn = get_db(); c = conn.cursor()
    c.execute('''INSERT INTO cars (model, rating, price, horsepower, acceleration, top_speed,
                                   image_data, image_mime, created_at)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)''',
              (model, rating, price, horsepower, acceleration, top_speed,
               psycopg2.Binary(data), mime, datetime.now().isoformat()))
    conn.commit(); c.close(); conn.close()


def update_car(car_id, model, rating, price, horsepower, acceleration, top_speed):
    conn = get_db(); c = conn.cursor()
    c.execute('''UPDATE cars SET model = %s, rating = %s, price = %s,
                 horsepower = %s, acceleration = %s, top_speed = %s
                 WHERE id = %s''',
              (model, rating, price, horsepower, acceleration, top_speed, car_id))
    conn.commit(); c.close(); conn.close()


def get_car_image(car_id):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT image_data, image_mime FROM cars WHERE id = %s', (car_id,))
    row = c.fetchone(); c.close(); conn.close()
    return row


def get_car_info(car_id):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT id, model, rating, price FROM cars WHERE id = %s', (car_id,))
    row = c.fetchone(); c.close(); conn.close()
    return row


def get_car_full(car_id):
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT id, model, rating, price, horsepower, acceleration, top_speed
                 FROM cars WHERE id = %s''', (car_id,))
    row = c.fetchone(); c.close(); conn.close()
    if not row: return None
    return {'id': row[0], 'model': row[1], 'rating': row[2], 'price': row[3] or 0,
            'horsepower': row[4], 'acceleration': row[5], 'top_speed': row[6]}


def delete_car_from_catalog(car_id):
    conn = get_db(); c = conn.cursor()
    c.execute('DELETE FROM user_cars WHERE car_id = %s', (car_id,))
    c.execute('DELETE FROM public_cars WHERE car_id = %s', (car_id,))
    c.execute('UPDATE users SET favorite_car_id = NULL WHERE favorite_car_id = %s', (car_id,))
    c.execute('DELETE FROM daily_discount WHERE car_id = %s', (car_id,))
    c.execute('DELETE FROM cars WHERE id = %s', (car_id,))
    conn.commit(); c.close(); conn.close()


# ---------- ЛИЧНЫЙ ГАРАЖ ----------
def get_user_cars(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT c.id, c.model, c.rating, c.price FROM cars c
                 JOIN user_cars uc ON uc.car_id = c.id WHERE uc.user_id = %s ORDER BY uc.id DESC''',
              (user_id,))
    rows = c.fetchall(); c.close(); conn.close()
    return rows


def count_user_cars(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM user_cars WHERE user_id = %s', (user_id,))
    r = c.fetchone(); c.close(); conn.close()
    return r[0] if r else 0


def has_car(user_id, car_id):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT 1 FROM user_cars WHERE user_id = %s AND car_id = %s', (user_id, car_id))
    r = c.fetchone(); c.close(); conn.close()
    return r is not None


def buy_car(user_id, car_id):
    if has_car(user_id, car_id): return False, 'Эта машина уже в твоём гараже'
    car = get_car_info(car_id)
    if not car: return False, 'Машина не найдена'
    discount = get_active_discount()
    final_price = car[3] or 0
    was_disc = False
    if discount and discount['car_id'] == car_id:
        final_price = int(final_price * (100 - discount['discount_percent']) / 100)
        was_disc = True
    balance = get_balance(user_id)
    if balance < final_price:
        return False, f'Не хватает монет. Нужно {final_price}, у тебя {balance}'
    conn = get_db(); c = conn.cursor()
    c.execute('UPDATE users SET balance = COALESCE(balance, 0) - %s WHERE id = %s', (final_price, user_id))
    c.execute('INSERT INTO user_cars (user_id, car_id, opened_at) VALUES (%s, %s, %s)',
              (user_id, car_id, datetime.now().isoformat()))
    conn.commit(); c.close(); conn.close()
    desc = f'Покупка: {car[1]}' + (' (со скидкой дня)' if was_disc else '')
    log_transaction(user_id, 'buy', -final_price, car_id, desc)
    return True, f'Куплена «{car[1]}» за {final_price} монет!'


def sell_car(user_id, car_id):
    if not has_car(user_id, car_id): return False, 'У тебя нет этой машины', 0
    car = get_car_info(car_id)
    if not car: return False, 'Машина не найдена', 0
    refund = int((car[3] or 0) * SELL_RATE)
    conn = get_db(); c = conn.cursor()
    c.execute('DELETE FROM user_cars WHERE user_id = %s AND car_id = %s', (user_id, car_id))
    c.execute('DELETE FROM public_cars WHERE user_id = %s AND car_id = %s', (user_id, car_id))
    c.execute('UPDATE users SET favorite_car_id = NULL WHERE id = %s AND favorite_car_id = %s',
              (user_id, car_id))
    c.execute('UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE id = %s', (refund, user_id))
    conn.commit(); c.close(); conn.close()
    log_transaction(user_id, 'sell', refund, car_id, f'Продажа: {car[1]}')
    return True, f'«{car[1]}» продана за {refund} монет', refund


# ---------- СКИДКА ДНЯ ----------
def get_active_discount():
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT id, car_id, discount_percent, set_at, expires_at FROM daily_discount '
              'ORDER BY id DESC LIMIT 1')
    row = c.fetchone(); c.close(); conn.close()
    if not row: return None
    try: expires = datetime.fromisoformat(row[4])
    except: return None
    if expires <= datetime.now(): return None
    return {'id': row[0], 'car_id': row[1], 'discount_percent': row[2]}


def roll_new_discount():
    if get_setting('discount_enabled') != '1': return None
    min_r = get_int_setting('discount_min_rating', 1)
    max_r = get_int_setting('discount_max_rating', 3)
    percent = get_int_setting('discount_percent', 50)
    candidates = get_catalog_by_rating(min_r, max_r)
    if not candidates: return None
    chosen = random.choice(candidates)
    conn = get_db(); c = conn.cursor()
    c.execute('DELETE FROM daily_discount')
    c.execute('INSERT INTO daily_discount (car_id, discount_percent, set_at, expires_at) '
              'VALUES (%s, %s, %s, %s)',
              (chosen[0], percent, datetime.now().isoformat(),
               (datetime.now() + timedelta(hours=24)).isoformat()))
    conn.commit(); c.close(); conn.close()
    return {'car_id': chosen[0], 'model': chosen[1], 'discount_percent': percent}


def ensure_discount():
    if get_active_discount() is None:
        return roll_new_discount()
    return None


# ---------- КОЛЕСО ----------
def can_spin(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT last_spin_at FROM users WHERE id = %s', (user_id,))
    row = c.fetchone(); c.close(); conn.close()
    cooldown = get_int_setting('wheel_cooldown_hours', 24) * 3600
    if not row or not row[0]: return True, 0
    try: last = datetime.fromisoformat(row[0])
    except: return True, 0
    diff = (datetime.now() - last).total_seconds()
    if diff >= cooldown: return True, 0
    return False, int(cooldown - diff)


def do_spin(user_id, paid=False):
    """Крутит колесо. Возвращает dict с результатом или {'error': '...'}."""
    if paid:
        price = get_int_setting('paid_wheel_price', 300)
        if get_balance(user_id) < price:
            return {'error': f'Нужно {price} монет'}
        add_coins(user_id, -price)
        log_transaction(user_id, 'paid_wheel_spend', -price, None, 'Премиум-колесо')
        car_chance = get_int_setting('paid_wheel_car_chance', 30)
        coin_min = get_int_setting('paid_wheel_coin_min', 200)
        coin_max = get_int_setting('paid_wheel_coin_max', 2000)
        min_r = get_int_setting('paid_wheel_car_min_rating', 4)
        max_r = get_int_setting('paid_wheel_car_max_rating', 8)
        coins_tx, car_tx = 'paid_wheel_coins', 'paid_wheel_car'
        prefix = 'Премиум-колесо'
    else:
        ready, _ = can_spin(user_id)
        if not ready:
            return {'error': 'Колесо пока недоступно'}
        conn = get_db(); c = conn.cursor()
        c.execute('UPDATE users SET last_spin_at = %s WHERE id = %s',
                  (datetime.now().isoformat(), user_id))
        conn.commit(); c.close(); conn.close()
        car_chance = get_int_setting('wheel_car_chance', 10)
        coin_min = get_int_setting('wheel_coin_min', 50)
        coin_max = get_int_setting('wheel_coin_max', 500)
        min_r = get_int_setting('wheel_car_min_rating', 1)
        max_r = get_int_setting('wheel_car_max_rating', 5)
        coins_tx, car_tx = 'wheel_coins', 'wheel_car'
        prefix = 'Колесо'

    roll = random.randint(1, 100)
    if roll <= car_chance:
        candidates = [c for c in get_catalog_by_rating(min_r, max_r) if not has_car(user_id, c[0])]
        if candidates:
            chosen = random.choice(candidates)
            conn = get_db(); c = conn.cursor()
            c.execute('INSERT INTO user_cars (user_id, car_id, opened_at) VALUES (%s, %s, %s)',
                      (user_id, chosen[0], datetime.now().isoformat()))
            conn.commit(); c.close(); conn.close()
            log_transaction(user_id, car_tx, 0, chosen[0], f'{prefix}: {chosen[1]}')
            return {'type': 'car', 'paid': paid, 'car_id': chosen[0],
                    'model': chosen[1], 'rating': chosen[2]}

    amount = random.randint(coin_min, coin_max)
    add_coins(user_id, amount)
    log_transaction(user_id, coins_tx, amount, None, f'{prefix}: монеты')
    return {'type': 'coins', 'paid': paid, 'amount': amount}


# ---------- ХЕЛПЕРЫ ----------
def is_admin(username):
    return username in ADMIN_USERNAMES


def login_required(f):
    @wraps(f)
    def deco(*a, **k):
        if 'user_id' not in session:
            flash('Сначала войди в аккаунт'); return redirect(url_for('login'))
        return f(*a, **k)
    return deco


def admin_required(f):
    @wraps(f)
    def deco(*a, **k):
        if 'user_id' not in session:
            flash('Сначала войди в аккаунт'); return redirect(url_for('login'))
        if not is_admin(session.get('username')):
            flash('Доступ только для администратора'); return redirect(url_for('index'))
        return f(*a, **k)
    return deco


ALLOWED_MIME = {'image/png', 'image/jpeg', 'image/webp', 'image/gif'}


def flash_new_achievements(user_id):
    """Проверяет достижения и флешит новые."""
    new = check_achievements(user_id)
    for key in new:
        for a in ACHIEVEMENTS:
            if a['key'] == key:
                flash(f'{a["icon"]} Достижение: «{a["title"]}» — {a["desc"]}')


# ---------- МАРШРУТЫ ----------
@app.route('/')
def index():
    profile = None; favorite_car = None; cars_count = 0
    bonus_ready = False; bonus_left = ''
    spin_ready = False; spin_left = ''
    achievements_count = 0
    incoming_trades_count = 0
    if 'user_id' in session:
        flash_new_achievements(session['user_id'])
        profile = get_user_profile(session['user_id'])
        if profile and profile['favorite_car_id']:
            favorite_car = get_car_info(profile['favorite_car_id'])
        cars_count = count_user_cars(session['user_id'])
        bonus_ready, secs = can_claim_bonus(session['user_id'])
        if not bonus_ready: bonus_left = format_time_left(secs)
        spin_ready, secs2 = can_spin(session['user_id'])
        if not spin_ready: spin_left = format_time_left(secs2)
        achievements_count = len(get_unlocked_keys(session['user_id']))
        incoming_trades_count = count_incoming_trades(session['user_id'])
    return render_template('index.html',
                           user=session.get('username'), profile=profile,
                           favorite_car=favorite_car, cars_count=cars_count,
                           bonus_ready=bonus_ready, bonus_left=bonus_left,
                           spin_ready=spin_ready, spin_left=spin_left,
                           achievements_count=achievements_count,
                           total_achievements=len(ACHIEVEMENTS),
                           incoming_trades_count=incoming_trades_count,
                           is_admin=is_admin(session.get('username')))


@app.route('/bonus', methods=['POST'])
@login_required
def bonus():
    ready, _ = can_claim_bonus(session['user_id'])
    if ready:
        claim_bonus(session['user_id'])
        flash(f'🎁 Ежедневный бонус: +{DAILY_BONUS} монет!')
    else:
        flash('Бонус пока недоступен')
    return redirect(url_for('index'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        password2 = request.form.get('password2', '')
        if not username or not password: flash('Заполни все поля'); return redirect(url_for('register'))
        if len(username) < 3 or len(username) > 20: flash('Ник от 3 до 20'); return redirect(url_for('register'))
        if len(password) < 6: flash('Пароль от 6 символов'); return redirect(url_for('register'))
        if password != password2: flash('Пароли не совпадают'); return redirect(url_for('register'))
        if get_user(username): flash('Ник занят'); return redirect(url_for('register'))
        create_user(username, password)
        user = get_user(username)
        session['user_id'] = user[0]; session['username'] = user[1]
        flash(f'Добро пожаловать! +{START_BALANCE} монет')
        return redirect(url_for('index'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = get_user(username)
        if user and check_password_hash(user[2], password):
            session['user_id'] = user[0]; session['username'] = user[1]
            return redirect(url_for('index'))
        flash('Неверный никнейм или пароль'); return redirect(url_for('login'))
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('user_id', None); session.pop('username', None)
    return redirect(url_for('index'))


# ---------- ПРОФИЛЬ ----------
@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    import traceback
    try:
        user_id = session['user_id']
        if request.method == 'POST':
            bio = request.form.get('bio', '').strip()[:200]
            fav = request.form.get('favorite_car_id', '').strip()
            fav_id = None
            if fav and fav.isdigit() and has_car(user_id, int(fav)):
                fav_id = int(fav)
            file = request.files.get('avatar')
            if file and file.filename != '':
                if file.mimetype in ALLOWED_MIME:
                    update_avatar(user_id, file.read(), file.mimetype)
                else:
                    flash('Аватарка: только PNG, JPG, WEBP, GIF')
                    return redirect(url_for('settings'))
            public_ids = [int(x) for x in request.form.getlist('public_cars') if x.isdigit()]
            my_ids = {c[0] for c in get_user_cars(user_id)}
            public_ids = [x for x in public_ids if x in my_ids]
            set_public_cars(user_id, public_ids)
            update_profile(user_id, bio, fav_id)
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
    except Exception:
        return '<h2 style="color:red;">Ошибка в /settings:</h2><pre style="font-size:14px;padding:20px;background:#fff0f0;white-space:pre-wrap;">' + traceback.format_exc() + '</pre>', 500


@app.route('/avatar/<int:user_id>')
def avatar(user_id):
    row = get_user_avatar(user_id)
    if not row or not row[0]: return '', 404
    return Response(bytes(row[0]), mimetype=row[1] or 'image/png')


@app.route('/profile/<username>')
def profile_page(username):
    import traceback
    try:
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
        achievements = get_achievements_for_user(user_row[0])
        return render_template('profile.html',
                               profile=profile,
                               favorite_car=favorite_car,
                               public_cars=public_cars,
                               cars_count=cars_count,
                               achievements=achievements,
                               user=session.get('username'),
                               is_admin=is_admin(session.get('username')))
    except Exception:
        return '<h2 style="color:red;">Ошибка в /profile:</h2><pre style="font-size:14px;padding:20px;background:#fff0f0;white-space:pre-wrap;">' + traceback.format_exc() + '</pre>', 500

# ---------- ГАРАЖ ----------
@app.route('/garage')
@login_required
def garage():
    flash_new_achievements(session['user_id'])
    return render_template('garage.html', cars=get_user_cars(session['user_id']),
                           balance=get_balance(session['user_id']),
                           user=session.get('username'),
                           is_admin=is_admin(session.get('username')))


@app.route('/garage/remove/<int:car_id>', methods=['POST'])
@login_required
def remove_from_garage(car_id):
    _, msg, _ = sell_car(session['user_id'], car_id)
    flash(msg)
    return redirect(url_for('garage'))


# ---------- МАГАЗИН ----------
@app.route('/shop')
@login_required
def shop():
    try:
        ensure_discount()
        discount = get_active_discount()
        balance = get_balance(session['user_id'])
        settings = {k: get_setting(k) for k in DEFAULT_SETTINGS}
        cars = []
        for car in get_catalog():
            cid, model, rating, price = car
            price = price or 0
            final_price = price
            has_disc = False
            if discount and discount['car_id'] == cid:
                final_price = int(price * (100 - discount['discount_percent']) / 100)
                has_disc = True
            cars.append({'id': cid, 'model': model, 'rating': rating, 'price': price,
                         'final_price': final_price, 'has_discount': has_disc,
                         'owned': has_car(session['user_id'], cid)})
        return render_template('shop.html', cars=cars, balance=balance, discount=discount,
                               settings=settings,
                               user=session.get('username'),
                               is_admin=is_admin(session.get('username')))
    except Exception:
        import traceback
        return '<h2 style="color:red;">Ошибка в /shop:</h2><pre style="font-size:14px;padding:20px;background:#fff0f0;white-space:pre-wrap;">' + traceback.format_exc() + '</pre>', 500


@app.route('/shop/buy/<int:car_id>', methods=['POST'])
@login_required
def shop_buy(car_id):
    _, msg = buy_car(session['user_id'], car_id)
    flash(msg)
    return redirect(url_for('shop'))


@app.route('/shop/add', methods=['GET', 'POST'])
@admin_required
def add_car_page():
    if request.method == 'POST':
        model = request.form.get('model', '').strip()
        rating = request.form.get('rating', '3')
        price = request.form.get('price', '500')
        hp = request.form.get('horsepower', '').strip()
        accel = request.form.get('acceleration', '').strip()
        top = request.form.get('top_speed', '').strip()
        file = request.files.get('image')

        if not model:
            flash('Впиши название'); return redirect(url_for('add_car_page'))
        try:
            rating = int(rating)
            if rating < 1 or rating > 8: raise ValueError
        except ValueError:
            flash('Оценка 1–8'); return redirect(url_for('add_car_page'))
        try:
            price = int(price)
            if price < 0: raise ValueError
        except ValueError:
            flash('Цена — число >= 0'); return redirect(url_for('add_car_page'))

        hp = int(hp) if hp.isdigit() else None
        top = int(top) if top.isdigit() else None
        try:
            accel = float(accel) if accel else None
        except ValueError:
            accel = None

        if not file or file.filename == '':
            flash('Выбери картинку'); return redirect(url_for('add_car_page'))
        if file.mimetype not in ALLOWED_MIME:
            flash('Формат PNG/JPG/WEBP/GIF'); return redirect(url_for('add_car_page'))

        add_car(model, rating, price, hp, accel, top, file.read(), file.mimetype)
        flash(f'«{model}» добавлена!')
        return redirect(url_for('shop'))
    return render_template('add_car.html', user=session.get('username'), is_admin=True)


@app.route('/shop/edit/<int:car_id>', methods=['GET', 'POST'])
@admin_required
def edit_car_page(car_id):
    car = get_car_full(car_id)
    if not car: flash('Нет машины'); return redirect(url_for('shop'))
    if request.method == 'POST':
        model = request.form.get('model', '').strip()
        rating = request.form.get('rating', '3')
        price = request.form.get('price', '500')
        hp = request.form.get('horsepower', '').strip()
        accel = request.form.get('acceleration', '').strip()
        top = request.form.get('top_speed', '').strip()

        if not model: flash('Впиши название'); return redirect(url_for('edit_car_page', car_id=car_id))
        try:
            rating = int(rating)
            if rating < 1 or rating > 8: raise ValueError
        except ValueError:
            flash('Оценка 1–8'); return redirect(url_for('edit_car_page', car_id=car_id))
        try:
            price = int(price)
            if price < 0: raise ValueError
        except ValueError:
            flash('Цена — число >= 0'); return redirect(url_for('edit_car_page', car_id=car_id))

        hp = int(hp) if hp.isdigit() else None
        top = int(top) if top.isdigit() else None
        try:
            accel = float(accel) if accel else None
        except ValueError:
            accel = None

        update_car(car_id, model, rating, price, hp, accel, top)
        flash('Машина обновлена')
        return redirect(url_for('shop'))
    return render_template('edit_car.html', car=car, user=session.get('username'), is_admin=True)


@app.route('/shop/delete/<int:car_id>', methods=['POST'])
@admin_required
def delete_from_catalog(car_id):
    delete_car_from_catalog(car_id)
    flash('Удалено')
    return redirect(url_for('shop'))


# ---------- КОЛЕСО ----------
@app.route('/wheel')
@login_required
def wheel():
    flash_new_achievements(session['user_id'])
    ready, secs = can_spin(session['user_id'])
    result = session.pop('wheel_result', None)
    paid_enabled = get_setting('paid_wheel_enabled') == '1'
    paid_price = get_int_setting('paid_wheel_price', 300)
    paid_info = {
        'car_chance': get_int_setting('paid_wheel_car_chance', 30),
        'coin_min': get_int_setting('paid_wheel_coin_min', 200),
        'coin_max': get_int_setting('paid_wheel_coin_max', 2000),
        'car_min_rating': get_int_setting('paid_wheel_car_min_rating', 4),
        'car_max_rating': get_int_setting('paid_wheel_car_max_rating', 8),
    }
    free_info = {
        'car_chance': get_int_setting('wheel_car_chance', 10),
        'coin_min': get_int_setting('wheel_coin_min', 50),
        'coin_max': get_int_setting('wheel_coin_max', 500),
        'car_min_rating': get_int_setting('wheel_car_min_rating', 1),
        'car_max_rating': get_int_setting('wheel_car_max_rating', 5),
    }
    return render_template('wheel.html',
                           ready=ready, time_left=format_time_left(secs) if not ready else '',
                           result=result, balance=get_balance(session['user_id']),
                           paid_enabled=paid_enabled, paid_price=paid_price,
                           paid_info=paid_info, free_info=free_info,
                           user=session.get('username'),
                           is_admin=is_admin(session.get('username')))


@app.route('/wheel/spin', methods=['POST'])
@login_required
def wheel_spin():
    result = do_spin(session['user_id'], paid=False)
    if 'error' in result: flash(result['error'])
    else: session['wheel_result'] = result
    return redirect(url_for('wheel'))


@app.route('/wheel/spin_paid', methods=['POST'])
@login_required
def wheel_spin_paid():
    if get_setting('paid_wheel_enabled') != '1':
        flash('Премиум-колесо отключено'); return redirect(url_for('wheel'))
    result = do_spin(session['user_id'], paid=True)
    if 'error' in result: flash(result['error'])
    else: session['wheel_result'] = result
    return redirect(url_for('wheel'))


# ---------- ЖУРНАЛ ----------
@app.route('/journal')
@login_required
def journal():
    return render_template('journal.html',
                           transactions=get_user_transactions(session['user_id']),
                           balance=get_balance(session['user_id']),
                           user=session.get('username'),
                           is_admin=is_admin(session.get('username')))


# ---------- ДОСТИЖЕНИЯ ----------
@app.route('/achievements')
@login_required
def achievements_page():
    flash_new_achievements(session['user_id'])
    achievements = get_achievements_for_user(session['user_id'])
    unlocked = sum(1 for a in achievements if a['unlocked'])
    return render_template('achievements.html', achievements=achievements,
                           unlocked_count=unlocked, total=len(achievements),
                           user=session.get('username'),
                           is_admin=is_admin(session.get('username')))

# ---------- ОБМЕНЫ ----------
@app.route('/trades')
@login_required
def trades_page():
    import traceback
    try:
        incoming = get_incoming_trades(session['user_id'])
        outgoing = [t for t in get_outgoing_trades(session['user_id']) if t['status'] == 'pending']
        history = get_trade_history(session['user_id'])
        return render_template('trades.html',
                               incoming=incoming, outgoing=outgoing, history=history,
                               balance=get_balance(session['user_id']),
                               my_id=session['user_id'],
                               user=session.get('username'),
                               is_admin=is_admin(session.get('username')))
    except Exception:
        return '<h2 style="color:red;">Ошибка в /trades:</h2><pre style="font-size:14px;padding:20px;background:#fff0f0;white-space:pre-wrap;">' + traceback.format_exc() + '</pre>', 500


@app.route('/trades/new', methods=['GET', 'POST'])
@login_required
def trade_new():
    if request.method == 'POST':
        to_username = request.form.get('to_username', '').strip()
        from_car_id = request.form.get('from_car_id', '')
        from_coins = request.form.get('from_coins', '0')
        message = request.form.get('message', '').strip()
        if not to_username:
            flash('Впиши ник игрока'); return redirect(url_for('trade_new'))
        if not from_car_id.isdigit():
            flash('Выбери свою машину'); return redirect(url_for('trade_new'))
        try:
            from_coins = int(from_coins or 0)
        except ValueError:
            flash('Монеты должны быть числом'); return redirect(url_for('trade_new'))
        ok, result = create_trade(session['user_id'], to_username, int(from_car_id),
                                  from_coins, message)
        if ok:
            flash('Предложение отправлено!')
            return redirect(url_for('trades_page'))
        flash(result); return redirect(url_for('trade_new'))
    my_cars = get_user_cars(session['user_id'])
    balance = get_balance(session['user_id'])
    return render_template('trade_new.html', my_cars=my_cars, balance=balance,
                           user=session.get('username'),
                           is_admin=is_admin(session.get('username')))


@app.route('/trades/<int:trade_id>')
@login_required
def trade_view(trade_id):
    import traceback
    try:
        t = get_trade_full(trade_id)
        if not t:
            flash('Обмен не найден'); return redirect(url_for('trades_page'))
        if t['from_user_id'] != session['user_id'] and t['to_user_id'] != session['user_id']:
            flash('Это не твой обмен'); return redirect(url_for('trades_page'))
        my_cars = get_user_cars(session['user_id']) if t['to_user_id'] == session['user_id'] else []
        balance = get_balance(session['user_id'])
        return render_template('trade_view.html', trade=t, my_cars=my_cars, balance=balance,
                               my_id=session['user_id'],
                               user=session.get('username'),
                               is_admin=is_admin(session.get('username')))
    except Exception:
        return '<h2 style="color:red;">Ошибка в /trades/<id>:</h2><pre style="font-size:14px;padding:20px;background:#fff0f0;white-space:pre-wrap;">' + traceback.format_exc() + '</pre>', 500
@app.route('/trades/<int:trade_id>/accept', methods=['POST'])
@login_required
def trade_accept(trade_id):
    to_car_raw = request.form.get('to_car_id', '').strip()
    to_coins = request.form.get('to_coins', '0')
    to_car_id = int(to_car_raw) if to_car_raw.isdigit() else None
    try:
        to_coins = int(to_coins or 0)
    except ValueError:
        flash('Монеты должны быть числом')
        return redirect(url_for('trade_view', trade_id=trade_id))
    ok, msg = accept_trade(trade_id, session['user_id'], to_car_id, to_coins)
    flash(msg)
    return redirect(url_for('trades_page'))


@app.route('/trades/<int:trade_id>/reject', methods=['POST'])
@login_required
def trade_reject(trade_id):
    ok, msg = reject_trade(trade_id, session['user_id'])
    flash(msg)
    return redirect(url_for('trades_page'))


@app.route('/trades/<int:trade_id>/cancel', methods=['POST'])
@login_required
def trade_cancel(trade_id):
    ok, msg = cancel_trade(trade_id, session['user_id'])
    flash(msg)
    return redirect(url_for('trades_page'))

# ---------- АДМИН-НАСТРОЙКИ ----------
@app.route('/admin/settings', methods=['GET', 'POST'])
@admin_required
def admin_settings():
    if request.method == 'POST':
        for k in ['discount_min_rating', 'discount_max_rating', 'discount_percent',
                  'wheel_coin_min', 'wheel_coin_max', 'wheel_car_chance',
                  'wheel_car_min_rating', 'wheel_car_max_rating', 'wheel_cooldown_hours',
                  'paid_wheel_price', 'paid_wheel_coin_min', 'paid_wheel_coin_max',
                  'paid_wheel_car_chance', 'paid_wheel_car_min_rating', 'paid_wheel_car_max_rating']:
            set_setting(k, request.form.get(k, get_setting(k)))
        for k in ['discount_enabled', 'wheel_enabled', 'paid_wheel_enabled']:
            set_setting(k, '1' if request.form.get(k) else '0')
        flash('Настройки сохранены!')
        return redirect(url_for('admin_settings'))
    settings = {k: get_setting(k) for k in DEFAULT_SETTINGS}
    discount = get_active_discount()
    discount_car = get_car_info(discount['car_id']) if discount else None
    return render_template('admin_settings.html', settings=settings,
                           discount=discount, discount_car=discount_car,
                           user=session.get('username'), is_admin=True)


@app.route('/admin/discount/reroll', methods=['POST'])
@admin_required
def admin_reroll_discount():
    try:
        conn = get_db(); c = conn.cursor()
        c.execute('DELETE FROM daily_discount'); conn.commit(); c.close(); conn.close()
        r = roll_new_discount()
        if r:
            flash(f'Новая скидка: «{r["model"]}» — {r["discount_percent"]}%')
        else:
            flash('Не удалось выбрать машину. Проверь диапазон рейтинга в настройках.')
        return redirect(url_for('admin_settings'))
    except Exception:
        import traceback
        return '<h2 style="color:red;">Ошибка в /admin/discount/reroll:</h2><pre style="font-size:14px;padding:20px;background:#fff0f0;white-space:pre-wrap;">' + traceback.format_exc() + '</pre>', 500


# ---------- КАРТИНКИ ----------
@app.route('/car_image/<int:car_id>')
def car_image(car_id):
    row = get_car_image(car_id)
    if not row: return '', 404
    return Response(bytes(row[0]), mimetype=row[1])

@app.route('/car/<int:car_id>')
def car_detail(car_id):
    car = get_car_full(car_id)
    if not car:
        flash('Машина не найдена')
        return redirect(url_for('index'))
    owned = False
    if 'user_id' in session:
        owned = has_car(session['user_id'], car_id)
    return render_template('car_detail.html', car=car, owned=owned,
                           user=session.get('username'),
                           is_admin=is_admin(session.get('username')))

# ---------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (для шаблонов) ----------
def get_public_ids(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT car_id FROM public_cars WHERE user_id = %s', (user_id,))
    rows = c.fetchall(); c.close(); conn.close()
    return {r[0] for r in rows}


def get_public_cars(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT c.id, c.model, c.rating, c.price FROM cars c
                 JOIN public_cars pc ON pc.car_id = c.id WHERE pc.user_id = %s ORDER BY pc.id DESC''',
              (user_id,))
    rows = c.fetchall(); c.close(); conn.close()
    return rows


def set_public_cars(user_id, car_ids):
    conn = get_db(); c = conn.cursor()
    c.execute('DELETE FROM public_cars WHERE user_id = %s', (user_id,))
    for cid in car_ids:
        c.execute('INSERT INTO public_cars (user_id, car_id) VALUES (%s, %s) '
                  'ON CONFLICT (user_id, car_id) DO NOTHING', (user_id, cid))
    conn.commit(); c.close(); conn.close()


init_db()

if __name__ == '__main__':
    app.run(debug=True)

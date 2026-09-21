from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash, Response, make_response)
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import psycopg2
import psycopg2.extras
import os
import random
import csv
import io
import zipfile
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-me-please')

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    raise RuntimeError('Не найдена переменная DATABASE_URL.')
DATABASE_URL = DATABASE_URL.replace('?sslmode=require', '').replace('&sslmode=require', '')

app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

# ============ ЭКОНОМИКА ============
START_BALANCE = 500
DAILY_BONUS = 100
SELL_RATE = 0.7
BONUS_COOLDOWN = 86400
BONUS_STREAK_MAX = 30
BONUS_STREAK_STEP = 25
BONUS_STREAK_MAX_AMOUNT = 500
STREAK_BREAK_HOURS = 48

# ============ ГОНКИ ============
RACE_LUCK_CHANCE = 20
RACE_TIMEOUT_MIN = 15
RACE_MIN_BET_TABLE = {1: 25, 2: 100, 3: 225, 4: 400, 5: 625, 6: 900, 7: 1225, 8: 1600}

# ============ УРОВНИ ============
MAX_LEVEL = 100
STAR_LEVEL_REQ = {1: 1, 2: 1, 3: 1, 4: 3, 5: 6, 6: 12, 7: 20, 8: 30}

XP_REWARDS = {
    'bonus': 25, 'buy': 30, 'sell': 10,
    'race_win': 50, 'race_lose': 15, 'trade': 40,
    'achievement': 100, 'wheel_free': 15, 'wheel_paid': 25,
    'quest': 0, 'quest_bonus': 400, 'collection': 500,
}

# ============ ЕЖЕДНЕВНЫЕ ЗАДАНИЯ ============
QUEST_POOL = [
    {'key': 'win_races_3',    'icon': '🏁', 'title': 'Победи в 3 гонках',      'target': 3, 'xp': 200, 'coins': 300},
    {'key': 'buy_car_1',      'icon': '🛒', 'title': 'Купи машину',            'target': 1, 'xp': 100, 'coins': 200},
    {'key': 'trade_1',        'icon': '🔄', 'title': 'Сделай обмен',           'target': 1, 'xp': 150, 'coins': 250},
    {'key': 'spin_wheel_1',   'icon': '🎡', 'title': 'Покрути колесо',         'target': 1, 'xp': 50,  'coins': 100},
    {'key': 'achievement_1',  'icon': '🏆', 'title': 'Открой достижение',      'target': 1, 'xp': 100, 'coins': 250},
    {'key': 'sell_car_1',     'icon': '💵', 'title': 'Продай машину',          'target': 1, 'xp': 30,  'coins': 80},
    {'key': 'races_play_5',   'icon': '🏎️', 'title': 'Сыграй 5 гонок',         'target': 5, 'xp': 120, 'coins': 180},
]
QUESTS_PER_DAY = 3
QUEST_BONUS_XP = 400
QUEST_BONUS_COINS = 500

# ============ КОЛЛЕКЦИИ ============
COLLECTION_RARITY = {
    'common':    {'label': 'Обычная',      'icon': '⚪', 'coins': 500,   'bonus': 50},
    'rare':      {'label': 'Редкая',       'icon': '🔵', 'coins': 2000,  'bonus': 200},
    'legendary': {'label': 'Легендарная',  'icon': '🟡', 'coins': 10000, 'bonus': 1000},
}
COLLECTION_ACH_REWARD = 500

# ============ АДМИНЫ ============
ADMIN_USERNAMES = {'AppleAT', 'Arbu3k52'}

# ============ НАСТРОЙКИ ПО УМОЛЧАНИЮ ============
DEFAULT_SETTINGS = {
    'discount_enabled': '1', 'discount_min_rating': '1', 'discount_max_rating': '3',
    'discount_percent': '50',
    'wheel_enabled': '1', 'wheel_coin_min': '30', 'wheel_coin_max': '150',
    'wheel_car_chance': '5', 'wheel_car_min_rating': '1', 'wheel_car_max_rating': '4',
    'wheel_cooldown_hours': '24',
    'paid_wheel_enabled': '1', 'paid_wheel_price': '1000',
    'paid_wheel_coin_min': '100', 'paid_wheel_coin_max': '600',
    'paid_wheel_car_chance': '15', 'paid_wheel_car_min_rating': '5', 'paid_wheel_car_max_rating': '8',
}

# ============ ДОСТИЖЕНИЯ ============
ACHIEVEMENTS = [
    {'key': 'first_car',   'icon': '🚗', 'title': 'Первая ласточка',  'desc': 'Получить первую машину в гараж', 'reward': 100},
    {'key': 'cars_5',      'icon': '🏎️', 'title': 'Коллекционер',     'desc': 'Собрать 5 машин',                'reward': 250},
    {'key': 'cars_10',     'icon': '🏁', 'title': 'Автолюбитель',     'desc': 'Собрать 10 машин',               'reward': 500},
    {'key': 'cars_25',     'icon': '🏛️', 'title': 'Автомузей',        'desc': 'Собрать 25 машин',               'reward': 1000},
    {'key': 'cars_50',     'icon': '👑', 'title': 'Мега-коллекция',   'desc': 'Собрать 50 машин',               'reward': 2500},
    {'key': 'cars_100',    'icon': '🏆', 'title': 'Автолегенда',      'desc': 'Собрать 100 машин',              'reward': 5000},
    {'key': 'cars_200',    'icon': '🌟', 'title': 'Автоимперия',      'desc': 'Собрать 200 машин',              'reward': 15000},
    {'key': 'rich_1000',   'icon': '💰', 'title': 'Богач',            'desc': 'Накопить 1000 монет',            'reward': 100},
    {'key': 'rich_5000',   'icon': '💎', 'title': 'Миллионер',        'desc': 'Накопить 5000 монет',            'reward': 500},
    {'key': 'rich_10000',  'icon': '🏦', 'title': 'Банкир',           'desc': 'Накопить 10 000 монет',          'reward': 1000},
    {'key': 'rich_50000',  'icon': '💼', 'title': 'Магнат',           'desc': 'Накопить 50 000 монет',          'reward': 3000},
    {'key': 'rich_100000', 'icon': '🏛️', 'title': 'Олигарх',          'desc': 'Накопить 100 000 монет',         'reward': 10000},
    {'key': 'first_sell',  'icon': '💵', 'title': 'Первый обмен',     'desc': 'Продать первую машину',          'reward': 100},
    {'key': 'bonus_3',     'icon': '🎁', 'title': 'Бонус-охотник',    'desc': 'Забрать бонус 3 раза',           'reward': 200},
    {'key': 'bonus_7',     'icon': '📅', 'title': 'Верный игрок',     'desc': 'Забрать бонус 7 раз',            'reward': 500},
    {'key': 'bonus_30',    'icon': '🔥', 'title': 'Преданный',        'desc': 'Забрать бонус 30 раз',           'reward': 2000},
    {'key': 'spin_5',      'icon': '🎡', 'title': 'Колесник',         'desc': 'Покрутить колесо 5 раз',         'reward': 200},
    {'key': 'spin_20',     'icon': '🎰', 'title': 'Азартный',         'desc': 'Покрутить колесо 20 раз',        'reward': 800},
    {'key': 'spin_100',    'icon': '🎲', 'title': 'Лудоман',          'desc': 'Покрутить колесо 100 раз',       'reward': 3000},
    {'key': 'lucky_car',   'icon': '🍀', 'title': 'Счастливчик',      'desc': 'Выиграть машину в колесе',       'reward': 300},
    {'key': 'five_star',   'icon': '⭐', 'title': 'Пятизвёздочный',   'desc': 'Владеть машиной с 5★ или выше',  'reward': 300},
    {'key': 'seven_star',  'icon': '💫', 'title': 'Семизвёздочный',   'desc': 'Владеть машиной с 7★',           'reward': 1500},
    {'key': 'eight_star',  'icon': '🌟', 'title': 'Легенда',          'desc': 'Владеть машиной с 8★',           'reward': 5000},
    {'key': 'premium',     'icon': '💎', 'title': 'VIP',              'desc': 'Крутить премиум-колесо',         'reward': 200},
    {'key': 'big_spender', 'icon': '🤑', 'title': 'Транжира',         'desc': 'Купить 10 машин',               'reward': 500},
    {'key': 'big_spender_50','icon':'💸', 'title': 'Тратитель',       'desc': 'Купить 50 машин',               'reward': 3000},
    {'key': 'big_spender_100','icon':'💳','title': 'Меценат',         'desc': 'Купить 100 машин',              'reward': 10000},
    {'key': 'first_friend','icon': '🤝', 'title': 'Не один',          'desc': 'Добавить первого друга',         'reward': 150},
    {'key': 'friends_5',   'icon': '👥', 'title': 'Компания',         'desc': 'Собрать 5 друзей',               'reward': 500},
    {'key': 'level_5',     'icon': '📈', 'title': 'Расту',            'desc': 'Достичь 5 уровня',              'reward': 200},
    {'key': 'level_10',    'icon': '📊', 'title': 'Опытный',          'desc': 'Достичь 10 уровня',             'reward': 500},
    {'key': 'level_20',    'icon': '🎯', 'title': 'Ветеран',          'desc': 'Достичь 20 уровня',             'reward': 1500},
    {'key': 'level_30',    'icon': '🏅', 'title': 'Мастер',           'desc': 'Достичь 30 уровня',             'reward': 3000},
    {'key': 'level_50',    'icon': '👑', 'title': 'Гуру',             'desc': 'Достичь 50 уровня',             'reward': 10000},
    {'key': 'quest_10',    'icon': '📜', 'title': 'Исполнитель',      'desc': 'Выполнить 10 заданий',          'reward': 500},
    {'key': 'quest_50',    'icon': '📖', 'title': 'Трудяга',          'desc': 'Выполнить 50 заданий',          'reward': 2000},
    {'key': 'race_win_10', 'icon': '🥇', 'title': 'Гонщик',           'desc': 'Победить в 10 гонках',          'reward': 500},
    {'key': 'race_win_50', 'icon': '🏆', 'title': 'Чемпион',          'desc': 'Победить в 50 гонках',          'reward': 2500},
    {'key': 'collector_1', 'icon': '📦', 'title': 'Начинающий коллекционер', 'desc': 'Собрать первую коллекцию', 'reward': 500},
    {'key': 'collector_3', 'icon': '📚', 'title': 'Знаток',           'desc': 'Собрать 3 коллекции',            'reward': 1500},
    {'key': 'collector_5', 'icon': '🎓', 'title': 'Эксперт',          'desc': 'Собрать 5 коллекций',            'reward': 3000},
    {'key': 'collector_10','icon': '💼', 'title': 'Антиквар',         'desc': 'Собрать 10 коллекций',           'reward': 10000},
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
    c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS login_streak INTEGER DEFAULT 0')
    c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS xp INTEGER DEFAULT 0')
    c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS level INTEGER DEFAULT 1')
    c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS sound_enabled BOOLEAN DEFAULT TRUE')
    c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS music_enabled BOOLEAN DEFAULT FALSE')
    c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS vibration_enabled BOOLEAN DEFAULT TRUE')
    c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS dark_theme BOOLEAN DEFAULT FALSE')

    c.execute('''CREATE TABLE IF NOT EXISTS cars (
        id SERIAL PRIMARY KEY, model VARCHAR(60) NOT NULL, rating INTEGER NOT NULL,
        image_data BYTEA NOT NULL, image_mime TEXT NOT NULL, created_at TEXT NOT NULL
    )''')
    c.execute('ALTER TABLE cars ADD COLUMN IF NOT EXISTS price INTEGER')
    c.execute('ALTER TABLE cars ADD COLUMN IF NOT EXISTS horsepower INTEGER')
    c.execute('ALTER TABLE cars ADD COLUMN IF NOT EXISTS acceleration REAL')
    c.execute('ALTER TABLE cars ADD COLUMN IF NOT EXISTS top_speed INTEGER')
    c.execute('ALTER TABLE cars ADD COLUMN IF NOT EXISTS brand VARCHAR(40)')
    c.execute('ALTER TABLE cars ADD COLUMN IF NOT EXISTS is_exclusive BOOLEAN DEFAULT FALSE')

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
        from_user_id INTEGER NOT NULL, to_user_id INTEGER NOT NULL,
        from_car_id INTEGER NOT NULL, from_coins INTEGER NOT NULL DEFAULT 0,
        to_car_id INTEGER, to_coins INTEGER NOT NULL DEFAULT 0,
        message TEXT, status VARCHAR(20) NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL, resolved_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS race_challenges (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL, car_id INTEGER NOT NULL,
        bet INTEGER NOT NULL, offer_car BOOLEAN NOT NULL DEFAULT FALSE,
        hide_car BOOLEAN NOT NULL DEFAULT FALSE,
        status VARCHAR(20) NOT NULL DEFAULT 'open',
        opponent_id INTEGER, opponent_car_id INTEGER, winner_id INTEGER,
        created_at TEXT NOT NULL, completed_at TEXT
    )''')
    c.execute('ALTER TABLE race_challenges ADD COLUMN IF NOT EXISTS hide_car BOOLEAN DEFAULT FALSE')
    c.execute('''CREATE TABLE IF NOT EXISTS favorite_cars (
        id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, car_id INTEGER NOT NULL,
        created_at TEXT NOT NULL, UNIQUE(user_id, car_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS wishlist (
        id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, car_id INTEGER NOT NULL,
        created_at TEXT NOT NULL, UNIQUE(user_id, car_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS friendships (
        id SERIAL PRIMARY KEY, from_user_id INTEGER NOT NULL, to_user_id INTEGER NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL, resolved_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_quests (
        id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL,
        quest_key VARCHAR(40) NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
        target INTEGER NOT NULL, xp_reward INTEGER NOT NULL, coins_reward INTEGER NOT NULL,
        completed BOOLEAN NOT NULL DEFAULT FALSE, claimed BOOLEAN NOT NULL DEFAULT FALSE,
        assigned_date TEXT NOT NULL,
        UNIQUE(user_id, quest_key, assigned_date)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS quest_bonus (
        id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, claimed_date TEXT NOT NULL,
        UNIQUE(user_id, claimed_date)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS completed_quests (
        id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL,
        quest_key VARCHAR(40) NOT NULL, completed_at TEXT NOT NULL
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS collections (
        id SERIAL PRIMARY KEY, name VARCHAR(80) NOT NULL, description TEXT,
        rarity VARCHAR(20) NOT NULL DEFAULT 'common',
        coins_reward INTEGER NOT NULL DEFAULT 500, bonus_coins INTEGER NOT NULL DEFAULT 50,
        exclusive_car_id INTEGER, created_at TEXT NOT NULL
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS collection_cars (
        id SERIAL PRIMARY KEY, collection_id INTEGER NOT NULL, car_id INTEGER NOT NULL,
        UNIQUE(collection_id, car_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_collections (
        id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, collection_id INTEGER NOT NULL,
        completed_at TEXT, main_claimed BOOLEAN NOT NULL DEFAULT FALSE,
        UNIQUE(user_id, collection_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_collection_bonus (
        id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, collection_id INTEGER NOT NULL,
        car_id INTEGER NOT NULL, claimed_at TEXT NOT NULL,
        UNIQUE(user_id, collection_id, car_id)
    )''')

    c.execute('UPDATE users SET balance = %s WHERE balance IS NULL', (START_BALANCE,))
    c.execute('UPDATE users SET xp = 0 WHERE xp IS NULL')
    c.execute('UPDATE users SET level = 1 WHERE level IS NULL')
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


# ---------- УРОВНИ ----------
def xp_for_level(level):
    return 100 + (level - 1) * 70


def level_reward_coins(level):
    return 100 + level * 30


def get_user_level_info(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT xp, level FROM users WHERE id = %s', (user_id,))
    row = c.fetchone(); c.close(); conn.close()
    if not row:
        return {'xp': 0, 'level': 1, 'xp_current': 0, 'xp_needed': xp_for_level(1), 'progress': 0}
    xp, level = row[0] or 0, row[1] or 1
    xp_needed = xp_for_level(level)
    progress = min(100, int(xp * 100 / xp_needed)) if xp_needed else 0
    return {'xp': xp, 'level': level, 'xp_current': xp, 'xp_needed': xp_needed, 'progress': progress}


def add_xp(user_id, amount):
    if amount <= 0:
        return False, 0, 0
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT xp, level FROM users WHERE id = %s', (user_id,))
    row = c.fetchone()
    if not row:
        c.close(); conn.close(); return False, 0, 0
    xp, level = row[0] or 0, row[1] or 1
    xp += amount
    leveled = False
    coins_reward = 0
    while level < MAX_LEVEL and xp >= xp_for_level(level):
        xp -= xp_for_level(level)
        level += 1
        leveled = True
        coins_reward += level_reward_coins(level)
    if level >= MAX_LEVEL:
        xp = 0
    c.execute('UPDATE users SET xp = %s, level = %s WHERE id = %s', (xp, level, user_id))
    if coins_reward > 0:
        c.execute('UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE id = %s',
                  (coins_reward, user_id))
    conn.commit(); c.close(); conn.close()
    if leveled and coins_reward > 0:
        log_transaction(user_id, 'levelup', coins_reward, None, f'Уровень {level}')
    return leveled, level, coins_reward


def get_level_required_for_stars(stars):
    return STAR_LEVEL_REQ.get(stars, 1)


# ---------- ЗАДАНИЯ ----------
def today_str():
    return datetime.now().strftime('%Y-%m-%d')


def get_user_quests(user_id):
    today = today_str()
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT quest_key, progress, target, xp_reward, coins_reward, completed, claimed
                 FROM user_quests WHERE user_id = %s AND assigned_date = %s ORDER BY id''',
              (user_id, today))
    rows = c.fetchall()
    if not rows:
        pool = random.sample(QUEST_POOL, QUESTS_PER_DAY)
        for q in pool:
            c.execute('''INSERT INTO user_quests
                         (user_id, quest_key, progress, target, xp_reward, coins_reward,
                          completed, claimed, assigned_date)
                         VALUES (%s, %s, 0, %s, %s, %s, FALSE, FALSE, %s)
                         ON CONFLICT (user_id, quest_key, assigned_date) DO NOTHING''',
                      (user_id, q['key'], q['target'], q['xp'], q['coins'], today))
        conn.commit()
        c.execute('''SELECT quest_key, progress, target, xp_reward, coins_reward, completed, claimed
                     FROM user_quests WHERE user_id = %s AND assigned_date = %s ORDER BY id''',
                  (user_id, today))
        rows = c.fetchall()
    c.close(); conn.close()

    conn = get_db(); c = conn.cursor()
    c.execute('SELECT 1 FROM quest_bonus WHERE user_id = %s AND claimed_date = %s', (user_id, today))
    bonus_claimed = c.fetchone() is not None
    c.close(); conn.close()

    result = []
    all_completed = True
    for r in rows:
        q = next((q for q in QUEST_POOL if q['key'] == r[0]), None)
        if not q: continue
        completed = bool(r[5])
        if not completed: all_completed = False
        result.append({'key': r[0], 'icon': q['icon'], 'title': q['title'],
                       'progress': r[1], 'target': r[2], 'xp': r[3], 'coins': r[4],
                       'completed': completed, 'claimed': bool(r[6])})
    return result, all_completed, bonus_claimed


def progress_quest(user_id, quest_key, amount=1):
    today = today_str()
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT id, progress, target, completed FROM user_quests
                 WHERE user_id = %s AND quest_key = %s AND assigned_date = %s''',
              (user_id, quest_key, today))
    row = c.fetchone()
    if not row:
        c.close(); conn.close(); return
    qid, progress, target, completed = row
    if completed:
        c.close(); conn.close(); return
    new_progress = min(target, progress + amount)
    new_completed = new_progress >= target
    c.execute('UPDATE user_quests SET progress = %s, completed = %s WHERE id = %s',
              (new_progress, new_completed, qid))
    conn.commit(); c.close(); conn.close()


def claim_quest(user_id, quest_key):
    today = today_str()
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT id, xp_reward, coins_reward, completed, claimed FROM user_quests
                 WHERE user_id = %s AND quest_key = %s AND assigned_date = %s''',
              (user_id, quest_key, today))
    row = c.fetchone()
    if not row:
        c.close(); conn.close(); return False, 'Задание не найдено'
    qid, xp, coins, completed, claimed = row
    if not completed:
        c.close(); conn.close(); return False, 'Задание ещё не выполнено'
    if claimed:
        c.close(); conn.close(); return False, 'Уже получено'
    c.execute('UPDATE user_quests SET claimed = TRUE WHERE id = %s', (qid,))
    c.execute('INSERT INTO completed_quests (user_id, quest_key, completed_at) VALUES (%s, %s, %s)',
              (user_id, quest_key, datetime.now().isoformat()))
    if coins > 0:
        c.execute('UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE id = %s', (coins, user_id))
    conn.commit(); c.close(); conn.close()
    if coins > 0:
        log_transaction(user_id, 'quest', coins, None, f'Задание выполнено')
    if xp > 0:
        add_xp(user_id, xp)
    return True, f'Задание сдано! +{coins} 💰, +{xp} XP'


def claim_quest_bonus(user_id):
    today = today_str()
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT COUNT(*) FROM user_quests
                 WHERE user_id = %s AND assigned_date = %s AND completed = TRUE''', (user_id, today))
    done = c.fetchone()[0]
    if done < QUESTS_PER_DAY:
        c.close(); conn.close(); return False, f'Сначала выполни все {QUESTS_PER_DAY} задания'
    c.execute('SELECT 1 FROM quest_bonus WHERE user_id = %s AND claimed_date = %s', (user_id, today))
    if c.fetchone():
        c.close(); conn.close(); return False, 'Бонус уже получен'
    c.execute('INSERT INTO quest_bonus (user_id, claimed_date) VALUES (%s, %s)', (user_id, today))
    c.execute('UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE id = %s',
              (QUEST_BONUS_COINS, user_id))
    conn.commit(); c.close(); conn.close()
    log_transaction(user_id, 'quest_bonus', QUEST_BONUS_COINS, None, 'Все задания выполнены')
    add_xp(user_id, QUEST_BONUS_XP)
    return True, f'Бонус! +{QUEST_BONUS_COINS} 💰, +{QUEST_BONUS_XP} XP'


def count_completed_quests(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM completed_quests WHERE user_id = %s', (user_id,))
    r = c.fetchone(); c.close(); conn.close()
    return r[0] if r else 0


# ---------- ПОЛЬЗОВАТЕЛИ ----------
def get_user(username):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT id, username, password_hash FROM users WHERE username = %s', (username,))
    row = c.fetchone(); c.close(); conn.close()
    return row


def create_user(username, password):
    conn = get_db(); c = conn.cursor()
    c.execute('INSERT INTO users (username, password_hash, created_at, balance, login_streak, xp, level) '
              'VALUES (%s, %s, %s, %s, 0, 0, 1)',
              (username, generate_password_hash(password), datetime.now().isoformat(), START_BALANCE))
    conn.commit(); c.close(); conn.close()


def get_username_by_id(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT username FROM users WHERE id = %s', (user_id,))
    row = c.fetchone(); c.close(); conn.close()
    return row[0] if row else '???'


def get_user_profile(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT id, username, avatar_data, avatar_mime, bio, favorite_car_id,
                        balance, login_streak, xp, level FROM users WHERE id = %s''', (user_id,))
    row = c.fetchone(); c.close(); conn.close()
    if not row: return None
    xp_needed = xp_for_level(row[9] or 1)
    return {'id': row[0], 'username': row[1], 'avatar_data': row[2], 'avatar_mime': row[3],
            'bio': row[4], 'favorite_car_id': row[5], 'balance': row[6] or 0,
            'login_streak': row[7] or 0, 'xp': row[8] or 0, 'level': row[9] or 1,
            'xp_needed': xp_needed}


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


def count_users():
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users')
    r = c.fetchone(); c.close(); conn.close()
    return r[0] if r else 0


# ---------- НАСТРОЙКИ ВНЕШНЕГО ВИДА ----------
def get_user_appearance(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT COALESCE(sound_enabled, TRUE),
                        COALESCE(music_enabled, FALSE),
                        COALESCE(vibration_enabled, TRUE),
                        COALESCE(dark_theme, FALSE)
                 FROM users WHERE id = %s''', (user_id,))
    row = c.fetchone(); c.close(); conn.close()
    if not row:
        return {'sound': True, 'music': False, 'vibration': True, 'dark': False}
    return {'sound': bool(row[0]), 'music': bool(row[1]),
            'vibration': bool(row[2]), 'dark': bool(row[3])}


def update_user_appearance(user_id, sound, music, vibration, dark):
    conn = get_db(); c = conn.cursor()
    c.execute('''UPDATE users SET sound_enabled = %s, music_enabled = %s,
                 vibration_enabled = %s, dark_theme = %s WHERE id = %s''',
              (sound, music, vibration, dark, user_id))
    conn.commit(); c.close(); conn.close()


# ---------- BULK UPLOAD ----------
MIME_BY_EXT = {
    'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
    'webp': 'image/webp', 'gif': 'image/gif'
}


def parse_bulk_csv(csv_bytes):
    errors = []
    rows = []
    try:
        text = csv_bytes.decode('utf-8-sig')
    except UnicodeDecodeError:
        try:
            text = csv_bytes.decode('cp1251')
        except UnicodeDecodeError:
            return [], ['Не удалось прочитать CSV. Сохрани в UTF-8 или Windows-1251.'], []

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return [], ['CSV пустой или не содержит заголовков.'], []

    headers = [h.strip().lower() for h in reader.fieldnames]
    required = {'model', 'brand', 'rating', 'price', 'image_filename'}
    missing = required - set(headers)
    if missing:
        return [], [f'В CSV не хватает колонок: {", ".join(sorted(missing))}'], headers

    for i, raw in enumerate(reader, start=2):
        row = {(k or '').strip().lower(): (v or '').strip() for k, v in raw.items()}
        model = row.get('model', '')
        brand = row.get('brand', '')
        image = row.get('image_filename', '')
        if not model and not brand and not image:
            continue
        row_errors = []
        if not model: row_errors.append('пустое поле model')
        if len(model) > 60: row_errors.append('model длиннее 60 символов')
        if not image: row_errors.append('пустое поле image_filename')
        try:
            rating = int(row.get('rating', ''))
            if rating < 1 or rating > 8: raise ValueError()
        except (ValueError, TypeError):
            row_errors.append(f'rating "{row.get("rating", "")}" не 1–8')
            rating = 1
        try:
            price = int(row.get('price', ''))
            if price < 0: raise ValueError()
        except (ValueError, TypeError):
            row_errors.append(f'price "{row.get("price", "")}" не число')
            price = 0
        hp = None
        if row.get('horsepower'):
            try: hp = int(row['horsepower'])
            except ValueError: row_errors.append('horsepower не число')
        accel = None
        if row.get('acceleration'):
            try: accel = float(row['acceleration'])
            except ValueError: row_errors.append('acceleration не число')
        top = None
        if row.get('top_speed'):
            try: top = int(row['top_speed'])
            except ValueError: row_errors.append('top_speed не число')
        is_excl = row.get('is_exclusive', '').lower() in ('1', 'true', 'yes', 'да')
        if row_errors:
            errors.append({'row': i, 'model': model or '(без названия)', 'errors': row_errors})
            continue
        rows.append({'row': i, 'model': model, 'brand': brand, 'rating': rating,
                     'price': price, 'horsepower': hp, 'acceleration': accel,
                     'top_speed': top, 'image_filename': image, 'is_exclusive': is_excl})
    return rows, errors, headers


def extract_zip_images(zip_bytes):
    images = {}
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for name in zf.namelist():
                if name.endswith('/'): continue
                base = os.path.basename(name).lower()
                if not base: continue
                ext = base.rsplit('.', 1)[-1] if '.' in base else ''
                if ext not in MIME_BY_EXT: continue
                try:
                    data = zf.read(name)
                except Exception:
                    continue
                images[base] = (data, MIME_BY_EXT[ext])
    except zipfile.BadZipFile:
        return None, 'Не удалось прочитать ZIP-архив.'
    return images, None


def bulk_insert_cars(rows, images, skip_existing=True):
    added = 0
    skipped_existing = 0
    skipped_no_image = 0
    errors = []
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT LOWER(model) FROM cars')
    existing = {r[0] for r in c.fetchall()}
    c.close(); conn.close()

    for row in rows:
        model_lower = row['model'].lower()
        if skip_existing and model_lower in existing:
            skipped_existing += 1
            continue
        img_name = row['image_filename'].lower()
        if img_name not in images:
            skipped_no_image += 1
            errors.append({'row': row['row'], 'model': row['model'],
                           'errors': [f'картинка «{row["image_filename"]}» не найдена']})
            continue
        data, mime = images[img_name]
        try:
            conn = get_db(); c = conn.cursor()
            c.execute('''INSERT INTO cars (model, brand, rating, price, horsepower,
                                           acceleration, top_speed, is_exclusive,
                                           image_data, image_mime, created_at)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                      (row['model'], row['brand'], row['rating'], row['price'],
                       row['horsepower'], row['acceleration'], row['top_speed'],
                       row['is_exclusive'], psycopg2.Binary(data), mime,
                       datetime.now().isoformat()))
            conn.commit(); c.close(); conn.close()
            existing.add(model_lower)
            added += 1
        except Exception as e:
            errors.append({'row': row['row'], 'model': row['model'],
                           'errors': [f'ошибка БД: {str(e)[:120]}']})
    return {'added': added, 'skipped_existing': skipped_existing,
            'skipped_no_image': skipped_no_image, 'errors': errors[:50],
            'errors_count': len(errors)}


# ---------- АДМИН: ВЫДАЧА ----------
def admin_give_coins(user_id, amount):
    if amount == 0:
        return False, 'Сумма не может быть нулевой'
    add_coins(user_id, amount)
    sign = '+' if amount > 0 else ''
    log_transaction(user_id, 'admin_give', amount, None, f'Админ: {sign}{amount} монет')
    return True, f'Выдано {sign}{amount} монет'


def admin_give_car(user_id, car_id):
    if has_car(user_id, car_id):
        return False, 'У игрока уже есть эта машина'
    car = get_car_info(car_id)
    if not car:
        return False, 'Машина не найдена'
    conn = get_db(); c = conn.cursor()
    c.execute('INSERT INTO user_cars (user_id, car_id, opened_at) VALUES (%s, %s, %s)',
              (user_id, car_id, datetime.now().isoformat()))
    c.execute('DELETE FROM wishlist WHERE user_id = %s AND car_id = %s', (user_id, car_id))
    conn.commit(); c.close(); conn.close()
    log_transaction(user_id, 'admin_give_car', 0, car_id, f'Админ: выдана «{car[1]}»')
    return True, f'Выдана «{car[1]}»'


def admin_take_car(user_id, car_id):
    if not has_car(user_id, car_id):
        return False, 'У игрока нет этой машины'
    car = get_car_info(car_id)
    conn = get_db(); c = conn.cursor()
    c.execute('DELETE FROM user_cars WHERE user_id = %s AND car_id = %s', (user_id, car_id))
    c.execute('DELETE FROM public_cars WHERE user_id = %s AND car_id = %s', (user_id, car_id))
    c.execute('DELETE FROM favorite_cars WHERE user_id = %s AND car_id = %s', (user_id, car_id))
    c.execute('UPDATE users SET favorite_car_id = NULL WHERE id = %s AND favorite_car_id = %s',
              (user_id, car_id))
    conn.commit(); c.close(); conn.close()
    log_transaction(user_id, 'admin_take_car', 0, car_id, f'Админ: забрана «{car[1]}»')
    return True, f'Забрана «{car[1]}»'


def admin_give_achievement(user_id, key):
    ach = next((a for a in ACHIEVEMENTS if a['key'] == key), None)
    if not ach:
        return False, 'Такого достижения нет'
    conn = get_db(); c = conn.cursor()
    c.execute('INSERT INTO user_achievements (user_id, key, unlocked_at) VALUES (%s, %s, %s) '
              'ON CONFLICT (user_id, key) DO NOTHING RETURNING id',
              (user_id, key, datetime.now().isoformat()))
    row = c.fetchone()
    conn.commit(); c.close(); conn.close()
    if not row:
        return False, 'У игрока уже есть это достижение'
    reward = ach['reward']
    if reward > 0:
        add_coins(user_id, reward)
        log_transaction(user_id, 'ach_reward', reward, None, f'Награда за «{ach["title"]}»')
    log_transaction(user_id, 'admin_give_ach', 0, None, f'Админ: достижение «{ach["title"]}»')
    return True, f'Выдано достижение «{ach["title"]}» (+{reward} 💰)'


def admin_take_achievement(user_id, key):
    conn = get_db(); c = conn.cursor()
    c.execute('DELETE FROM user_achievements WHERE user_id = %s AND key = %s RETURNING id',
              (user_id, key))
    row = c.fetchone()
    conn.commit(); c.close(); conn.close()
    if not row:
        return False, 'У игрока нет этого достижения'
    return True, 'Достижение убрано'


def admin_set_level(user_id, level):
    level = max(1, min(MAX_LEVEL, level))
    conn = get_db(); c = conn.cursor()
    c.execute('UPDATE users SET level = %s, xp = 0 WHERE id = %s', (level, user_id))
    conn.commit(); c.close(); conn.close()
    log_transaction(user_id, 'admin_set_level', 0, None, f'Админ: уровень = {level}')
    return True, f'Уровень установлен: {level}'


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


# ---------- ДРУЗЬЯ ----------
def get_friend_status(user_a, user_b):
    if user_a == user_b:
        return 'self'
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT from_user_id, status FROM friendships
                 WHERE (from_user_id = %s AND to_user_id = %s)
                    OR (from_user_id = %s AND to_user_id = %s)''', (user_a, user_b, user_b, user_a))
    row = c.fetchone(); c.close(); conn.close()
    if not row: return None
    from_id, status = row
    if status == 'accepted': return 'accepted'
    if status == 'pending':
        return 'pending_out' if from_id == user_a else 'pending_in'
    return None


def send_friend_request(from_id, to_username):
    to_user = get_user(to_username)
    if not to_user: return False, 'Игрок с таким ником не найден'
    to_id = to_user[0]
    if to_id == from_id: return False, 'Нельзя добавить себя'
    status = get_friend_status(from_id, to_id)
    if status == 'accepted': return False, 'Вы уже друзья'
    if status == 'pending_out': return False, 'Заявка уже отправлена'
    if status == 'pending_in': return False, 'Этот игрок уже отправил тебе заявку'
    conn = get_db(); c = conn.cursor()
    c.execute('''INSERT INTO friendships (from_user_id, to_user_id, status, created_at)
                 VALUES (%s, %s, 'pending', %s)''', (from_id, to_id, datetime.now().isoformat()))
    conn.commit(); c.close(); conn.close()
    return True, f'Заявка отправлена игроку {to_username}'


def accept_friend_request(request_id, user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT to_user_id, status FROM friendships WHERE id = %s', (request_id,))
    row = c.fetchone()
    if not row: c.close(); conn.close(); return False, 'Заявка не найдена'
    if row[0] != user_id: c.close(); conn.close(); return False, 'Это не твоя заявка'
    if row[1] != 'pending': c.close(); conn.close(); return False, 'Уже обработана'
    c.execute("UPDATE friendships SET status = 'accepted', resolved_at = %s WHERE id = %s",
              (datetime.now().isoformat(), request_id))
    conn.commit(); c.close(); conn.close()
    return True, 'Теперь вы друзья!'


def reject_friend_request(request_id, user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT to_user_id, status FROM friendships WHERE id = %s', (request_id,))
    row = c.fetchone()
    if not row: c.close(); conn.close(); return False, 'Заявка не найдена'
    if row[0] != user_id: c.close(); conn.close(); return False, 'Это не твоя заявка'
    if row[1] != 'pending': c.close(); conn.close(); return False, 'Уже обработана'
    c.execute('DELETE FROM friendships WHERE id = %s', (request_id,))
    conn.commit(); c.close(); conn.close()
    return True, 'Заявка отклонена'


def cancel_friend_request(request_id, user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT from_user_id, status FROM friendships WHERE id = %s', (request_id,))
    row = c.fetchone()
    if not row: c.close(); conn.close(); return False, 'Заявка не найдена'
    if row[0] != user_id: c.close(); conn.close(); return False, 'Это не твоя заявка'
    if row[1] != 'pending': c.close(); conn.close(); return False, 'Уже обработана'
    c.execute('DELETE FROM friendships WHERE id = %s', (request_id,))
    conn.commit(); c.close(); conn.close()
    return True, 'Заявка отменена'


def remove_friend(user_id, friend_id):
    conn = get_db(); c = conn.cursor()
    c.execute('''DELETE FROM friendships WHERE status = 'accepted'
                   AND ((from_user_id = %s AND to_user_id = %s)
                     OR (from_user_id = %s AND to_user_id = %s))''',
              (user_id, friend_id, friend_id, user_id))
    conn.commit(); c.close(); conn.close()
    return True, 'Удалено из друзей'


def get_friends(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT u.id, u.username, (u.avatar_data IS NOT NULL),
                        COALESCE(u.balance, 0), COALESCE(u.bio, ''), COALESCE(u.level, 1)
                 FROM friendships f
                 JOIN users u ON (u.id = f.from_user_id AND f.to_user_id = %s)
                              OR (u.id = f.to_user_id AND f.from_user_id = %s)
                 WHERE f.status = 'accepted' AND u.id != %s
                 ORDER BY u.level DESC, u.username''', (user_id, user_id, user_id))
    rows = c.fetchall(); c.close(); conn.close()
    return [{'id': r[0], 'username': r[1], 'has_avatar': r[2], 'balance': r[3],
             'bio': r[4], 'level': r[5], 'cars_count': count_user_cars(r[0])} for r in rows]


def get_incoming_requests(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT f.id, u.id, u.username, (u.avatar_data IS NOT NULL), f.created_at
                 FROM friendships f JOIN users u ON u.id = f.from_user_id
                 WHERE f.to_user_id = %s AND f.status = 'pending' ORDER BY f.id DESC''', (user_id,))
    rows = c.fetchall(); c.close(); conn.close()
    return [{'id': r[0], 'user_id': r[1], 'username': r[2], 'has_avatar': r[3], 'created_at': r[4]} for r in rows]


def get_outgoing_requests(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT f.id, u.id, u.username, (u.avatar_data IS NOT NULL), f.created_at
                 FROM friendships f JOIN users u ON u.id = f.to_user_id
                 WHERE f.from_user_id = %s AND f.status = 'pending' ORDER BY f.id DESC''', (user_id,))
    rows = c.fetchall(); c.close(); conn.close()
    return [{'id': r[0], 'user_id': r[1], 'username': r[2], 'has_avatar': r[3], 'created_at': r[4]} for r in rows]


def count_incoming_requests(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM friendships WHERE to_user_id = %s AND status = 'pending'", (user_id,))
    r = c.fetchone(); c.close(); conn.close()
    return r[0] if r else 0


def count_friends(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT COUNT(*) FROM friendships WHERE status = 'accepted'
                   AND (from_user_id = %s OR to_user_id = %s)''', (user_id, user_id))
    r = c.fetchone(); c.close(); conn.close()
    return r[0] if r else 0


def search_users(query, exclude_id):
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT id, username, (avatar_data IS NOT NULL), COALESCE(level, 1)
                 FROM users WHERE username ILIKE %s AND id != %s
                 ORDER BY level DESC, username LIMIT 20''', (query + '%', exclude_id))
    rows = c.fetchall(); c.close(); conn.close()
    return [{'id': r[0], 'username': r[1], 'has_avatar': r[2], 'level': r[3]} for r in rows]


# ---------- КОЛЛЕКЦИИ ----------
def get_collections():
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT id, name, description, rarity, coins_reward, bonus_coins, exclusive_car_id, created_at '
              'FROM collections ORDER BY id DESC')
    rows = c.fetchall(); c.close(); conn.close()
    return [{'id': r[0], 'name': r[1], 'description': r[2] or '', 'rarity': r[3],
             'coins_reward': r[4], 'bonus_coins': r[5], 'exclusive_car_id': r[6],
             'created_at': r[7]} for r in rows]


def get_collection(cid):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT id, name, description, rarity, coins_reward, bonus_coins, exclusive_car_id, created_at '
              'FROM collections WHERE id = %s', (cid,))
    row = c.fetchone(); c.close(); conn.close()
    if not row: return None
    return {'id': row[0], 'name': row[1], 'description': row[2] or '', 'rarity': row[3],
            'coins_reward': row[4], 'bonus_coins': row[5], 'exclusive_car_id': row[6],
            'created_at': row[7]}


def get_collection_cars(cid):
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT c.id, c.model, c.rating, c.price, c.brand FROM cars c
                 JOIN collection_cars cc ON cc.car_id = c.id
                 WHERE cc.collection_id = %s ORDER BY c.model''', (cid,))
    rows = c.fetchall(); c.close(); conn.close()
    return [{'id': r[0], 'model': r[1], 'rating': r[2], 'price': r[3] or 0, 'brand': r[4] or ''} for r in rows]


def create_collection(name, description, rarity, coins_reward, bonus_coins, exclusive_car_id, car_ids):
    conn = get_db(); c = conn.cursor()
    c.execute('''INSERT INTO collections (name, description, rarity, coins_reward, bonus_coins,
                                          exclusive_car_id, created_at)
                 VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id''',
              (name, description, rarity, coins_reward, bonus_coins, exclusive_car_id,
               datetime.now().isoformat()))
    cid = c.fetchone()[0]
    for car_id in car_ids:
        c.execute('INSERT INTO collection_cars (collection_id, car_id) VALUES (%s, %s) '
                  'ON CONFLICT (collection_id, car_id) DO NOTHING', (cid, car_id))
    conn.commit(); c.close(); conn.close()
    return cid


def update_collection(cid, name, description, rarity, coins_reward, bonus_coins, exclusive_car_id, car_ids):
    conn = get_db(); c = conn.cursor()
    c.execute('''UPDATE collections SET name = %s, description = %s, rarity = %s,
                 coins_reward = %s, bonus_coins = %s, exclusive_car_id = %s WHERE id = %s''',
              (name, description, rarity, coins_reward, bonus_coins, exclusive_car_id, cid))
    c.execute('DELETE FROM collection_cars WHERE collection_id = %s', (cid,))
    for car_id in car_ids:
        c.execute('INSERT INTO collection_cars (collection_id, car_id) VALUES (%s, %s) '
                  'ON CONFLICT (collection_id, car_id) DO NOTHING', (cid, car_id))
    conn.commit(); c.close(); conn.close()


def delete_collection(cid):
    conn = get_db(); c = conn.cursor()
    c.execute('DELETE FROM collection_cars WHERE collection_id = %s', (cid,))
    c.execute('DELETE FROM user_collections WHERE collection_id = %s', (cid,))
    c.execute('DELETE FROM user_collection_bonus WHERE collection_id = %s', (cid,))
    c.execute('DELETE FROM collections WHERE id = %s', (cid,))
    conn.commit(); c.close(); conn.close()


def get_collection_progress(user_id, cid):
    cars = get_collection_cars(cid)
    total = len(cars)
    owned_ids = set()
    if total > 0:
        conn = get_db(); c = conn.cursor()
        c.execute('SELECT car_id FROM user_cars WHERE user_id = %s', (user_id,))
        owned_ids = {r[0] for r in c.fetchall()}
        c.close(); conn.close()
    owned_count = sum(1 for car in cars if car['id'] in owned_ids)
    completed = total > 0 and owned_count == total

    conn = get_db(); c = conn.cursor()
    c.execute('SELECT completed_at, main_claimed FROM user_collections '
              'WHERE user_id = %s AND collection_id = %s', (user_id, cid))
    row = c.fetchone(); c.close(); conn.close()
    main_claimed = row[1] if row else False

    conn = get_db(); c = conn.cursor()
    c.execute('SELECT car_id FROM user_collection_bonus WHERE user_id = %s AND collection_id = %s',
              (user_id, cid))
    bonus_claimed_ids = {r[0] for r in c.fetchall()}
    c.close(); conn.close()

    if completed and not row:
        conn = get_db(); c = conn.cursor()
        c.execute('''INSERT INTO user_collections (user_id, collection_id, completed_at, main_claimed)
                     VALUES (%s, %s, %s, FALSE) ON CONFLICT (user_id, collection_id)
                     DO UPDATE SET completed_at = EXCLUDED.completed_at
                     WHERE user_collections.completed_at IS NULL''',
                  (user_id, cid, datetime.now().isoformat()))
        conn.commit(); c.close(); conn.close()

    bonus_available = []
    if main_claimed:
        for car in cars:
            if car['id'] in owned_ids and car['id'] not in bonus_claimed_ids:
                bonus_available.append(car)

    return {'total': total, 'owned': owned_count,
            'progress_pct': int(owned_count * 100 / total) if total else 0,
            'completed': completed, 'main_claimed': main_claimed,
            'bonus_claimed_ids': bonus_claimed_ids,
            'bonus_available': bonus_available,
            'owned_ids': owned_ids}


def get_all_collections_for_user(user_id):
    result = []
    for col in get_collections():
        prog = get_collection_progress(user_id, col['id'])
        col2 = dict(col)
        col2['progress'] = prog
        col2['rarity_info'] = COLLECTION_RARITY.get(col['rarity'], COLLECTION_RARITY['common'])
        result.append(col2)
    return result


def claim_collection_reward(user_id, cid):
    col = get_collection(cid)
    if not col: return False, 'Коллекция не найдена'
    prog = get_collection_progress(user_id, cid)
    if not prog['completed']:
        return False, 'Коллекция ещё не собрана'
    if prog['main_claimed']:
        return False, 'Награда уже получена'

    coins = col['coins_reward']
    if coins > 0:
        add_coins(user_id, coins)
        log_transaction(user_id, 'collection_reward', coins, None, f'Коллекция «{col["name"]}»')

    car_given = None
    if col['exclusive_car_id']:
        if not has_car(user_id, col['exclusive_car_id']):
            conn = get_db(); c = conn.cursor()
            c.execute('INSERT INTO user_cars (user_id, car_id, opened_at) VALUES (%s, %s, %s)',
                      (user_id, col['exclusive_car_id'], datetime.now().isoformat()))
            conn.commit(); c.close(); conn.close()
            car_given = get_car_info(col['exclusive_car_id'])
            log_transaction(user_id, 'collection_car', 0, col['exclusive_car_id'],
                            f'Эксклюзив коллекции «{col["name"]}»')

    conn = get_db(); c = conn.cursor()
    c.execute('UPDATE user_collections SET main_claimed = TRUE '
              'WHERE user_id = %s AND collection_id = %s', (user_id, cid))
    cars = get_collection_cars(cid)
    now = datetime.now().isoformat()
    for car in cars:
        if has_car(user_id, car['id']):
            c.execute('INSERT INTO user_collection_bonus (user_id, collection_id, car_id, claimed_at) '
                      'VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING',
                      (user_id, cid, car['id'], now))
    conn.commit(); c.close(); conn.close()

    add_xp(user_id, XP_REWARDS.get('collection', 500))
    _unlock_collection_achievement(user_id, cid)
    _check_collector_achievements(user_id)

    msg = f'🏆 Коллекция «{col["name"]}» собрана! +{coins} 💰'
    if car_given:
        msg += f' · Получена «{car_given[1]}»!'
    return True, msg


def claim_collection_bonus(user_id, cid, car_id):
    col = get_collection(cid)
    if not col: return False, 'Коллекция не найдена'
    prog = get_collection_progress(user_id, cid)
    if not prog['main_claimed']:
        return False, 'Сначала забери основную награду'
    if not has_car(user_id, car_id):
        return False, 'У тебя нет этой машины'
    cars = get_collection_cars(cid)
    if not any(car['id'] == car_id for car in cars):
        return False, 'Этой машины нет в коллекции'
    if car_id in prog['bonus_claimed_ids']:
        return False, 'Бонус за эту машину уже получен'
    bonus = col['bonus_coins']
    if bonus > 0:
        add_coins(user_id, bonus)
        log_transaction(user_id, 'collection_bonus', bonus, car_id, f'Бонус коллекции «{col["name"]}»')
    conn = get_db(); c = conn.cursor()
    c.execute('INSERT INTO user_collection_bonus (user_id, collection_id, car_id, claimed_at) '
              'VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING',
              (user_id, cid, car_id, datetime.now().isoformat()))
    conn.commit(); c.close(); conn.close()
    return True, f'Бонус получен: +{bonus} 💰'


def count_completed_collections(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM user_collections WHERE user_id = %s AND main_claimed = TRUE',
              (user_id,))
    r = c.fetchone(); c.close(); conn.close()
    return r[0] if r else 0


def _unlock_collection_achievement(user_id, cid):
    key = f'col_{cid}'
    conn = get_db(); c = conn.cursor()
    c.execute('INSERT INTO user_achievements (user_id, key, unlocked_at) VALUES (%s, %s, %s) '
              'ON CONFLICT (user_id, key) DO NOTHING',
              (user_id, key, datetime.now().isoformat()))
    conn.commit(); c.close(); conn.close()
    add_coins(user_id, COLLECTION_ACH_REWARD)
    log_transaction(user_id, 'ach_reward', COLLECTION_ACH_REWARD, None, 'Достижение коллекции')
    add_xp(user_id, XP_REWARDS.get('achievement', 100))


def _check_collector_achievements(user_id):
    count = count_completed_collections(user_id)
    already = get_unlocked_keys(user_id)
    checks = {'collector_1': count >= 1, 'collector_3': count >= 3,
              'collector_5': count >= 5, 'collector_10': count >= 10}
    for key, cond in checks.items():
        if key not in already and cond:
            conn = get_db(); c = conn.cursor()
            c.execute('INSERT INTO user_achievements (user_id, key, unlocked_at) VALUES (%s, %s, %s) '
                      'ON CONFLICT (user_id, key) DO NOTHING RETURNING id',
                      (user_id, key, datetime.now().isoformat()))
            row = c.fetchone()
            conn.commit(); c.close(); conn.close()
            if row:
                ach = next((a for a in ACHIEVEMENTS if a['key'] == key), None)
                if ach:
                    add_coins(user_id, ach['reward'])
                    log_transaction(user_id, 'ach_reward', ach['reward'], None, f'Награда за «{ach["title"]}»')


def get_collection_achievements_for_user(user_id):
    unlocked = get_unlocked_keys(user_id)
    result = []
    for col in get_collections():
        key = f'col_{col["id"]}'
        rarity_info = COLLECTION_RARITY.get(col['rarity'], COLLECTION_RARITY['common'])
        result.append({'key': key, 'icon': rarity_info['icon'],
                       'title': f'Коллекционер: {col["name"]}',
                       'desc': f'Собрать коллекцию «{col["name"]}»',
                       'reward': COLLECTION_ACH_REWARD,
                       'unlocked': key in unlocked, 'is_collection': True,
                       'collection_id': col['id']})
    return result


# ---------- ДОСТИЖЕНИЯ ----------
def get_unlocked_keys(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT key FROM user_achievements WHERE user_id = %s', (user_id,))
    rows = c.fetchall(); c.close(); conn.close()
    return {r[0] for r in rows}


def unlock_achievement(user_id, key):
    conn = get_db(); c = conn.cursor()
    c.execute('INSERT INTO user_achievements (user_id, key, unlocked_at) VALUES (%s, %s, %s) '
              'ON CONFLICT (user_id, key) DO NOTHING RETURNING id',
              (user_id, key, datetime.now().isoformat()))
    row = c.fetchone()
    conn.commit(); c.close(); conn.close()
    if not row: return False, 0
    ach = next((a for a in ACHIEVEMENTS if a['key'] == key), None)
    reward = ach['reward'] if ach else 0
    if reward > 0:
        add_coins(user_id, reward)
        log_transaction(user_id, 'ach_reward', reward, None, f'Награда за «{ach["title"]}»')
    progress_quest(user_id, 'achievement_1', 1)
    add_xp(user_id, XP_REWARDS.get('achievement', 100))
    return True, reward


def check_achievements(user_id):
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
    friends = count_friends(user_id)
    level = get_user_level_info(user_id)['level']
    quests_done = count_completed_quests(user_id)
    race_wins = count_tx(user_id, 'race_win')
    collections_done = count_completed_collections(user_id)

    checks = {
        'first_car':   cars_count >= 1, 'cars_5': cars_count >= 5,
        'cars_10':     cars_count >= 10, 'cars_25': cars_count >= 25,
        'cars_50':     cars_count >= 50, 'cars_100': cars_count >= 100,
        'cars_200':    cars_count >= 200,
        'rich_1000':   balance >= 1000, 'rich_5000': balance >= 5000,
        'rich_10000':  balance >= 10000, 'rich_50000': balance >= 50000,
        'rich_100000': balance >= 100000,
        'first_sell':  sells >= 1, 'bonus_3': bonuses >= 3,
        'bonus_7':     bonuses >= 7, 'bonus_30': bonuses >= 30,
        'spin_5':      spins >= 5, 'spin_20': spins >= 20, 'spin_100': spins >= 100,
        'lucky_car':   wheel_cars >= 1, 'five_star': max_rating >= 5,
        'seven_star':  max_rating >= 7, 'eight_star': max_rating >= 8,
        'premium':     paid_spins >= 1,
        'big_spender': buys >= 10, 'big_spender_50': buys >= 50,
        'big_spender_100': buys >= 100,
        'first_friend': friends >= 1, 'friends_5': friends >= 5,
        'level_5':     level >= 5, 'level_10': level >= 10,
        'level_20':    level >= 20, 'level_30': level >= 30, 'level_50': level >= 50,
        'quest_10':    quests_done >= 10, 'quest_50': quests_done >= 50,
        'race_win_10': race_wins >= 10, 'race_win_50': race_wins >= 50,
        'collector_1': collections_done >= 1, 'collector_3': collections_done >= 3,
        'collector_5': collections_done >= 5, 'collector_10': collections_done >= 10,
    }
    for key, cond in checks.items():
        if key not in already and cond:
            is_new, reward = unlock_achievement(user_id, key)
            if is_new:
                new_ones.append((key, reward))
    return new_ones


def get_max_car_rating(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT MAX(c.rating) FROM cars c
                 JOIN user_cars uc ON uc.car_id = c.id WHERE uc.user_id = %s''', (user_id,))
    r = c.fetchone(); c.close(); conn.close()
    return r[0] if r and r[0] else 0


def get_achievements_for_user(user_id):
    unlocked = get_unlocked_keys(user_id)
    result = [{**a, 'unlocked': a['key'] in unlocked} for a in ACHIEVEMENTS]
    result.extend(get_collection_achievements_for_user(user_id))
    return result


def flash_new_achievements(user_id):
    new = check_achievements(user_id)
    for key, reward in new:
        for a in ACHIEVEMENTS:
            if a['key'] == key:
                text = f'{a["icon"]} Достижение: «{a["title"]}»'
                if reward: text += f' · +{reward} 💰'
                flash(text)


# ---------- БОНУС / STREAK ----------
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


def get_bonus_preview(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT last_bonus_at, login_streak FROM users WHERE id = %s', (user_id,))
    row = c.fetchone(); c.close(); conn.close()
    if not row or not row[0]: return 1, DAILY_BONUS
    try: last = datetime.fromisoformat(row[0])
    except: return 1, DAILY_BONUS
    diff_hours = (datetime.now() - last).total_seconds() / 3600
    streak = min((row[1] or 0) + 1, BONUS_STREAK_MAX) if diff_hours <= STREAK_BREAK_HOURS else 1
    amount = min(DAILY_BONUS + (streak - 1) * BONUS_STREAK_STEP, BONUS_STREAK_MAX_AMOUNT)
    return streak, amount


def claim_bonus(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT last_bonus_at, login_streak FROM users WHERE id = %s', (user_id,))
    row = c.fetchone()
    streak = 1
    if row and row[0]:
        try:
            last = datetime.fromisoformat(row[0])
            diff_hours = (datetime.now() - last).total_seconds() / 3600
            if diff_hours <= STREAK_BREAK_HOURS:
                streak = min((row[1] or 0) + 1, BONUS_STREAK_MAX)
        except: pass
    amount = min(DAILY_BONUS + (streak - 1) * BONUS_STREAK_STEP, BONUS_STREAK_MAX_AMOUNT)
    c.execute('UPDATE users SET balance = COALESCE(balance, 0) + %s, last_bonus_at = %s, '
              'login_streak = %s WHERE id = %s',
              (amount, datetime.now().isoformat(), streak, user_id))
    conn.commit(); c.close(); conn.close()
    log_transaction(user_id, 'bonus', amount, None, f'Ежедневный бонус (серия {streak})')
    add_xp(user_id, XP_REWARDS.get('bonus', 25))
    return amount, streak


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


def get_all_brands():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT DISTINCT brand FROM cars WHERE brand IS NOT NULL AND brand != '' ORDER BY brand")
    rows = c.fetchall(); c.close(); conn.close()
    return [r[0] for r in rows]


def get_catalog_by_rating(min_r, max_r):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT id, model, rating, price FROM cars WHERE rating BETWEEN %s AND %s ORDER BY id DESC',
              (min_r, max_r))
    rows = c.fetchall(); c.close(); conn.close()
    return rows


def add_car(model, brand, rating, price, horsepower, acceleration, top_speed, is_exclusive, data, mime):
    conn = get_db(); c = conn.cursor()
    c.execute('''INSERT INTO cars (model, brand, rating, price, horsepower, acceleration,
                                   top_speed, is_exclusive, image_data, image_mime, created_at)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
              (model, brand, rating, price, horsepower, acceleration, top_speed, is_exclusive,
               psycopg2.Binary(data), mime, datetime.now().isoformat()))
    conn.commit(); c.close(); conn.close()


def update_car(car_id, model, brand, rating, price, horsepower, acceleration, top_speed, is_exclusive):
    conn = get_db(); c = conn.cursor()
    c.execute('''UPDATE cars SET model = %s, brand = %s, rating = %s, price = %s,
                 horsepower = %s, acceleration = %s, top_speed = %s, is_exclusive = %s WHERE id = %s''',
              (model, brand, rating, price, horsepower, acceleration, top_speed, is_exclusive, car_id))
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
    c.execute('''SELECT id, model, rating, price, horsepower, acceleration, top_speed, brand,
                        COALESCE(is_exclusive, FALSE) FROM cars WHERE id = %s''', (car_id,))
    row = c.fetchone(); c.close(); conn.close()
    if not row: return None
    return {'id': row[0], 'model': row[1], 'rating': row[2], 'price': row[3] or 0,
            'horsepower': row[4], 'acceleration': row[5], 'top_speed': row[6],
            'brand': row[7] or '', 'is_exclusive': row[8]}


def delete_car_from_catalog(car_id):
    conn = get_db(); c = conn.cursor()
    c.execute('DELETE FROM user_cars WHERE car_id = %s', (car_id,))
    c.execute('DELETE FROM public_cars WHERE car_id = %s', (car_id,))
    c.execute('DELETE FROM favorite_cars WHERE car_id = %s', (car_id,))
    c.execute('DELETE FROM wishlist WHERE car_id = %s', (car_id,))
    c.execute('UPDATE users SET favorite_car_id = NULL WHERE favorite_car_id = %s', (car_id,))
    c.execute('DELETE FROM daily_discount WHERE car_id = %s', (car_id,))
    c.execute('DELETE FROM collection_cars WHERE car_id = %s', (car_id,))
    c.execute('UPDATE collections SET exclusive_car_id = NULL WHERE exclusive_car_id = %s', (car_id,))
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
    car = get_car_full(car_id)
    if not car: return False, 'Машина не найдена'
    if car['is_exclusive']:
        return False, 'Эксклюзивные машины нельзя купить — только получить за коллекцию'
    req_level = get_level_required_for_stars(car['rating'])
    user_level = get_user_level_info(user_id)['level']
    if user_level < req_level:
        return False, f'Нужен {req_level} уровень для покупки {car["rating"]}★ машины'
    discount = get_active_discount()
    final_price = car['price']
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
    c.execute('DELETE FROM wishlist WHERE user_id = %s AND car_id = %s', (user_id, car_id))
    conn.commit(); c.close(); conn.close()
    desc = f'Покупка: {car["model"]}' + (' (со скидкой дня)' if was_disc else '')
    log_transaction(user_id, 'buy', -final_price, car_id, desc)
    add_xp(user_id, XP_REWARDS.get('buy', 30))
    progress_quest(user_id, 'buy_car_1', 1)
    return True, f'Куплена «{car["model"]}» за {final_price} монет!'


def sell_car(user_id, car_id):
    if not has_car(user_id, car_id): return False, 'У тебя нет этой машины', 0
    car = get_car_full(car_id)
    if not car: return False, 'Машина не найдена', 0
    refund = int(car['price'] * SELL_RATE)
    conn = get_db(); c = conn.cursor()
    c.execute('DELETE FROM user_cars WHERE user_id = %s AND car_id = %s', (user_id, car_id))
    c.execute('DELETE FROM public_cars WHERE user_id = %s AND car_id = %s', (user_id, car_id))
    c.execute('DELETE FROM favorite_cars WHERE user_id = %s AND car_id = %s', (user_id, car_id))
    c.execute('UPDATE users SET favorite_car_id = NULL WHERE id = %s AND favorite_car_id = %s',
              (user_id, car_id))
    c.execute('UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE id = %s', (refund, user_id))
    conn.commit(); c.close(); conn.close()
    log_transaction(user_id, 'sell', refund, car_id, f'Продажа: {car["model"]}')
    add_xp(user_id, XP_REWARDS.get('sell', 10))
    progress_quest(user_id, 'sell_car_1', 1)
    return True, f'«{car["model"]}» продана за {refund} монет', refund


# ---------- ИЗБРАННОЕ / ВИШЛИСТ ----------
def toggle_favorite(user_id, car_id):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT 1 FROM favorite_cars WHERE user_id = %s AND car_id = %s', (user_id, car_id))
    exists = c.fetchone()
    if exists:
        c.execute('DELETE FROM favorite_cars WHERE user_id = %s AND car_id = %s', (user_id, car_id))
        result = False
    else:
        c.execute('INSERT INTO favorite_cars (user_id, car_id, created_at) VALUES (%s, %s, %s)',
                  (user_id, car_id, datetime.now().isoformat()))
        result = True
    conn.commit(); c.close(); conn.close()
    return result


def get_favorite_ids(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT car_id FROM favorite_cars WHERE user_id = %s', (user_id,))
    rows = c.fetchall(); c.close(); conn.close()
    return {r[0] for r in rows}


def toggle_wishlist(user_id, car_id):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT 1 FROM wishlist WHERE user_id = %s AND car_id = %s', (user_id, car_id))
    exists = c.fetchone()
    if exists:
        c.execute('DELETE FROM wishlist WHERE user_id = %s AND car_id = %s', (user_id, car_id))
        result = False
    else:
        c.execute('INSERT INTO wishlist (user_id, car_id, created_at) VALUES (%s, %s, %s)',
                  (user_id, car_id, datetime.now().isoformat()))
        result = True
    conn.commit(); c.close(); conn.close()
    return result


def get_wishlist_ids(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('SELECT car_id FROM wishlist WHERE user_id = %s', (user_id,))
    rows = c.fetchall(); c.close(); conn.close()
    return {r[0] for r in rows}


def get_wishlist_cars(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT c.id, c.model, c.rating, c.price, w.created_at
                 FROM cars c JOIN wishlist w ON w.car_id = c.id
                 WHERE w.user_id = %s ORDER BY w.id DESC''', (user_id,))
    rows = c.fetchall(); c.close(); conn.close()
    return [{'id': r[0], 'model': r[1], 'rating': r[2], 'price': r[3] or 0} for r in rows]


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
    if paid:
        price = get_int_setting('paid_wheel_price', 1000)
        if get_balance(user_id) < price:
            return {'error': f'Нужно {price} монет'}
        add_coins(user_id, -price)
        log_transaction(user_id, 'paid_wheel_spend', -price, None, 'Премиум-колесо')
        car_chance = get_int_setting('paid_wheel_car_chance', 15)
        coin_min = get_int_setting('paid_wheel_coin_min', 100)
        coin_max = get_int_setting('paid_wheel_coin_max', 600)
        min_r = get_int_setting('paid_wheel_car_min_rating', 5)
        max_r = get_int_setting('paid_wheel_car_max_rating', 8)
        coins_tx, car_tx = 'paid_wheel_coins', 'paid_wheel_car'
        prefix = 'Премиум-колесо'
        xp_key = 'wheel_paid'
    else:
        ready, _ = can_spin(user_id)
        if not ready:
            return {'error': 'Колесо пока недоступно'}
        conn = get_db(); c = conn.cursor()
        c.execute('UPDATE users SET last_spin_at = %s WHERE id = %s',
                  (datetime.now().isoformat(), user_id))
        conn.commit(); c.close(); conn.close()
        car_chance = get_int_setting('wheel_car_chance', 5)
        coin_min = get_int_setting('wheel_coin_min', 30)
        coin_max = get_int_setting('wheel_coin_max', 150)
        min_r = get_int_setting('wheel_car_min_rating', 1)
        max_r = get_int_setting('wheel_car_max_rating', 4)
        coins_tx, car_tx = 'wheel_coins', 'wheel_car'
        prefix = 'Колесо'
        xp_key = 'wheel_free'

    add_xp(user_id, XP_REWARDS.get(xp_key, 15))
    progress_quest(user_id, 'spin_wheel_1', 1)

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


# ---------- ОБМЕНЫ ----------
def create_trade(from_user_id, to_username, from_car_id, from_coins, message):
    to_user = get_user(to_username)
    if not to_user: return False, 'Игрок с таким ником не найден'
    to_user_id = to_user[0]
    if to_user_id == from_user_id: return False, 'Нельзя самому себе'
    if not has_car(from_user_id, from_car_id): return False, 'У тебя нет этой машины'
    if from_coins < 0: return False, 'Монеты не могут быть отрицательными'
    if get_balance(from_user_id) < from_coins:
        return False, f'Не хватает монет. У тебя {get_balance(from_user_id)}'
    message = (message or '')[:200]
    conn = get_db(); c = conn.cursor()
    if from_coins > 0:
        c.execute('UPDATE users SET balance = COALESCE(balance, 0) - %s WHERE id = %s',
                  (from_coins, from_user_id))
    c.execute('''INSERT INTO trades
                 (from_user_id, to_user_id, from_car_id, from_coins, message, status, created_at)
                 VALUES (%s, %s, %s, %s, %s, 'pending', %s) RETURNING id''',
              (from_user_id, to_user_id, from_car_id, from_coins, message, datetime.now().isoformat()))
    trade_id = c.fetchone()[0]
    conn.commit(); c.close(); conn.close()
    if from_coins > 0:
        log_transaction(from_user_id, 'trade_reserve', -from_coins, from_car_id,
                        f'Заморожено для обмена с {to_username}')
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
    c.execute('''SELECT id FROM trades WHERE from_user_id = %s ORDER BY id DESC LIMIT 50''', (user_id,))
    ids = [r[0] for r in c.fetchall()]; c.close(); conn.close()
    return [get_trade_full(i) for i in ids]


def get_trade_history(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT id FROM trades WHERE (from_user_id = %s OR to_user_id = %s)
                 AND status IN ('completed', 'rejected', 'cancelled')
                 ORDER BY id DESC LIMIT 50''', (user_id, user_id))
    ids = [r[0] for r in c.fetchall()]; c.close(); conn.close()
    return [get_trade_full(i) for i in ids]


def count_incoming_trades(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT COUNT(*) FROM trades WHERE to_user_id = %s AND status = 'pending' ''', (user_id,))
    r = c.fetchone(); c.close(); conn.close()
    return r[0] if r else 0


def accept_trade(trade_id, user_id, to_car_id, to_coins):
    t = get_trade(trade_id)
    if not t: return False, 'Обмен не найден'
    if t['to_user_id'] != user_id: return False, 'Это не твой обмен'
    if t['status'] != 'pending': return False, 'Обмен уже обработан'
    if to_coins < 0: return False, 'Монеты не могут быть отрицательными'
    if get_balance(user_id) < to_coins:
        return False, f'У тебя только {get_balance(user_id)} монет'
    if not has_car(t['from_user_id'], t['from_car_id']):
        return False, 'У отправителя уже нет этой машины'
    if has_car(user_id, t['from_car_id']):
        return False, 'У тебя уже есть эта машина'
    if to_car_id:
        if not has_car(user_id, to_car_id): return False, 'У тебя нет этой машины'
        if has_car(t['from_user_id'], to_car_id):
            return False, 'У отправителя уже есть эта машина'

    conn = get_db(); c = conn.cursor()
    c.execute('DELETE FROM user_cars WHERE user_id = %s AND car_id = %s',
              (t['from_user_id'], t['from_car_id']))
    c.execute('''INSERT INTO user_cars (user_id, car_id, opened_at)
                 VALUES (%s, %s, %s) ON CONFLICT (user_id, car_id) DO NOTHING''',
              (user_id, t['from_car_id'], datetime.now().isoformat()))
    c.execute('DELETE FROM public_cars WHERE user_id = %s AND car_id = %s',
              (t['from_user_id'], t['from_car_id']))
    c.execute('DELETE FROM favorite_cars WHERE user_id = %s AND car_id = %s',
              (t['from_user_id'], t['from_car_id']))
    c.execute('UPDATE users SET favorite_car_id = NULL WHERE id = %s AND favorite_car_id = %s',
              (t['from_user_id'], t['from_car_id']))
    c.execute('DELETE FROM wishlist WHERE user_id = %s AND car_id = %s',
              (user_id, t['from_car_id']))

    if to_car_id:
        c.execute('DELETE FROM user_cars WHERE user_id = %s AND car_id = %s', (user_id, to_car_id))
        c.execute('''INSERT INTO user_cars (user_id, car_id, opened_at)
                     VALUES (%s, %s, %s) ON CONFLICT (user_id, car_id) DO NOTHING''',
                  (t['from_user_id'], to_car_id, datetime.now().isoformat()))
        c.execute('DELETE FROM public_cars WHERE user_id = %s AND car_id = %s', (user_id, to_car_id))
        c.execute('DELETE FROM favorite_cars WHERE user_id = %s AND car_id = %s', (user_id, to_car_id))
        c.execute('UPDATE users SET favorite_car_id = NULL WHERE id = %s AND favorite_car_id = %s',
                  (user_id, to_car_id))
        c.execute('DELETE FROM wishlist WHERE user_id = %s AND car_id = %s',
                  (t['from_user_id'], to_car_id))

    diff = t['from_coins'] - to_coins
    if diff > 0:
        c.execute('UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE id = %s', (diff, user_id))
    elif diff < 0:
        c.execute('UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE id = %s',
                  (-diff, t['from_user_id']))

    c.execute('''UPDATE trades SET to_car_id = %s, to_coins = %s,
                 status = 'completed', resolved_at = %s WHERE id = %s''',
              (to_car_id, to_coins, datetime.now().isoformat(), trade_id))
    conn.commit(); c.close(); conn.close()

    other_name = get_username_by_id(user_id)
    my_name = get_username_by_id(t['from_user_id'])
    log_transaction(t['from_user_id'], 'trade', -t['from_coins'] + to_coins,
                    t['from_car_id'], f'Обмен с {other_name}')
    log_transaction(user_id, 'trade', t['from_coins'] - to_coins, to_car_id, f'Обмен с {my_name}')
    add_xp(t['from_user_id'], XP_REWARDS.get('trade', 40))
    add_xp(user_id, XP_REWARDS.get('trade', 40))
    progress_quest(t['from_user_id'], 'trade_1', 1)
    progress_quest(user_id, 'trade_1', 1)
    return True, 'Обмен выполнен!'


def reject_trade(trade_id, user_id):
    t = get_trade(trade_id)
    if not t: return False, 'Не найден'
    if t['to_user_id'] != user_id: return False, 'Это не твой обмен'
    if t['status'] != 'pending': return False, 'Уже обработан'
    conn = get_db(); c = conn.cursor()
    if t['from_coins'] > 0:
        c.execute('UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE id = %s',
                  (t['from_coins'], t['from_user_id']))
    c.execute("UPDATE trades SET status = 'rejected', resolved_at = %s WHERE id = %s",
              (datetime.now().isoformat(), trade_id))
    conn.commit(); c.close(); conn.close()
    if t['from_coins'] > 0:
        log_transaction(t['from_user_id'], 'trade_refund', t['from_coins'], None, 'Возврат из отклонённого обмена')
    return True, 'Обмен отклонён'


def cancel_trade(trade_id, user_id):
    t = get_trade(trade_id)
    if not t: return False, 'Не найден'
    if t['from_user_id'] != user_id: return False, 'Это не твой обмен'
    if t['status'] != 'pending': return False, 'Уже обработан'
    conn = get_db(); c = conn.cursor()
    if t['from_coins'] > 0:
        c.execute('UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE id = %s',
                  (t['from_coins'], t['from_user_id']))
    c.execute("UPDATE trades SET status = 'cancelled', resolved_at = %s WHERE id = %s",
              (datetime.now().isoformat(), trade_id))
    conn.commit(); c.close(); conn.close()
    if t['from_coins'] > 0:
        log_transaction(t['from_user_id'], 'trade_refund', t['from_coins'], None, 'Возврат из отменённого обмена')
    return True, 'Обмен отменён'


# ---------- ГОНКИ ----------
def get_min_bet(rating):
    return RACE_MIN_BET_TABLE.get(rating, 25)


def car_score(car_dict):
    hp = car_dict.get('horsepower') or 100
    acc = car_dict.get('acceleration') or 10
    top = car_dict.get('top_speed') or 200
    return (hp / 100) + (100 / acc) + (top / 50)


def cleanup_expired_challenges():
    conn = get_db(); c = conn.cursor()
    cutoff = (datetime.now() - timedelta(minutes=RACE_TIMEOUT_MIN)).isoformat()
    c.execute("SELECT id, user_id, bet FROM race_challenges WHERE status = 'open' AND created_at < %s",
              (cutoff,))
    expired = c.fetchall()
    for row in expired:
        c.execute('UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE id = %s', (row[2], row[1]))
        log_transaction(row[1], 'race_refund', row[2], None, 'Возврат: вызов истёк')
    if expired:
        c.execute("UPDATE race_challenges SET status = 'expired', completed_at = %s "
                  "WHERE status = 'open' AND created_at < %s",
                  (datetime.now().isoformat(), cutoff))
        conn.commit()
    c.close(); conn.close()


def create_race_challenge(user_id, car_id, bet, offer_car, hide_car):
    car = get_car_full(car_id)
    if not car: return False, 'Машина не найдена'
    if not has_car(user_id, car_id): return False, 'У тебя нет этой машины'
    min_bet = get_min_bet(car['rating'])
    if bet < min_bet: return False, f'Мин. ставка для {car["rating"]}★ — {min_bet} монет'
    if get_balance(user_id) < bet: return False, f'Не хватает монет. У тебя {get_balance(user_id)}'
    conn = get_db(); c = conn.cursor()
    c.execute('UPDATE users SET balance = COALESCE(balance, 0) - %s WHERE id = %s', (bet, user_id))
    c.execute('''INSERT INTO race_challenges (user_id, car_id, bet, offer_car, hide_car, status, created_at)
                 VALUES (%s, %s, %s, %s, %s, 'open', %s) RETURNING id''',
              (user_id, car_id, bet, offer_car, hide_car, datetime.now().isoformat()))
    rid = c.fetchone()[0]
    conn.commit(); c.close(); conn.close()
    log_transaction(user_id, 'race_bet', -bet, car_id, 'Ставка на гонку')
    return True, rid


def get_open_challenges(exclude_user_id=None):
    cleanup_expired_challenges()
    conn = get_db(); c = conn.cursor()
    if exclude_user_id:
        c.execute("SELECT id, user_id, car_id, bet, offer_car, hide_car FROM race_challenges "
                  "WHERE status = 'open' AND user_id != %s ORDER BY id DESC", (exclude_user_id,))
    else:
        c.execute("SELECT id, user_id, car_id, bet, offer_car, hide_car FROM race_challenges "
                  "WHERE status = 'open' ORDER BY id DESC")
    rows = c.fetchall(); c.close(); conn.close()
    return [{'id': r[0], 'user_id': r[1], 'username': get_username_by_id(r[1]),
             'car': get_car_full(r[2]), 'bet': r[3], 'offer_car': r[4], 'hide_car': bool(r[5])} for r in rows]


def get_user_challenges(user_id):
    cleanup_expired_challenges()
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT id, user_id, car_id, bet, offer_car, hide_car FROM race_challenges "
              "WHERE status = 'open' AND user_id = %s ORDER BY id DESC", (user_id,))
    rows = c.fetchall(); c.close(); conn.close()
    return [{'id': r[0], 'user_id': r[1], 'username': get_username_by_id(r[1]),
             'car': get_car_full(r[2]), 'bet': r[3], 'offer_car': r[4], 'hide_car': bool(r[5])} for r in rows]


def cancel_race_challenge(challenge_id, user_id):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT user_id, bet, status FROM race_challenges WHERE id = %s", (challenge_id,))
    row = c.fetchone()
    if not row: c.close(); conn.close(); return False, 'Вызов не найден'
    if row[0] != user_id: c.close(); conn.close(); return False, 'Не твой вызов'
    if row[2] != 'open': c.close(); conn.close(); return False, 'Уже неактуален'
    c.execute('UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE id = %s', (row[1], user_id))
    c.execute("UPDATE race_challenges SET status = 'cancelled', completed_at = %s WHERE id = %s",
              (datetime.now().isoformat(), challenge_id))
    conn.commit(); c.close(); conn.close()
    log_transaction(user_id, 'race_refund', row[1], None, 'Возврат: отмена вызова')
    return True, 'Вызов отменён'


def join_race_challenge(challenge_id, user_id, my_car_id, offer_car):
    cleanup_expired_challenges()
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT user_id, car_id, bet, offer_car, status FROM race_challenges WHERE id = %s",
              (challenge_id,))
    row = c.fetchone()
    if not row:
        c.close(); conn.close(); return False, 'Вызов не найден', None
    author_id, author_car_id, bet, author_offer, status = row
    if status != 'open': c.close(); conn.close(); return False, 'Вызов уже занят', None
    if author_id == user_id: c.close(); conn.close(); return False, 'Нельзя принять свой вызов', None
    my_car = get_car_full(my_car_id)
    if not my_car or not has_car(user_id, my_car_id):
        c.close(); conn.close(); return False, 'Машина не найдена', None
    if get_balance(user_id) < bet:
        c.close(); conn.close(); return False, f'Нужна ставка {bet}, у тебя {get_balance(user_id)}', None

    car_stake = bool(author_offer) and bool(offer_car)
    c.execute('UPDATE users SET balance = COALESCE(balance, 0) - %s WHERE id = %s', (bet, user_id))

    author_car = get_car_full(author_car_id)
    p1_score = car_score(author_car)
    p2_score = car_score(my_car)

    if random.randint(1, 100) <= RACE_LUCK_CHANCE:
        winner_id = random.choice([author_id, user_id])
    else:
        winner_id = author_id if p1_score >= p2_score else user_id

    loser_id = user_id if winner_id == author_id else author_id
    bank = bet * 2
    c.execute('UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE id = %s', (bank, winner_id))

    car_transferred = False
    if car_stake:
        loser_car_id = author_car_id if loser_id == author_id else my_car_id
        c.execute('DELETE FROM user_cars WHERE user_id = %s AND car_id = %s', (loser_id, loser_car_id))
        c.execute('''INSERT INTO user_cars (user_id, car_id, opened_at)
                     VALUES (%s, %s, %s) ON CONFLICT (user_id, car_id) DO NOTHING''',
                  (winner_id, loser_car_id, datetime.now().isoformat()))
        c.execute('DELETE FROM public_cars WHERE user_id = %s AND car_id = %s', (loser_id, loser_car_id))
        c.execute('DELETE FROM favorite_cars WHERE user_id = %s AND car_id = %s', (loser_id, loser_car_id))
        c.execute('UPDATE users SET favorite_car_id = NULL WHERE id = %s AND favorite_car_id = %s',
                  (loser_id, loser_car_id))
        car_transferred = True

    c.execute('''UPDATE race_challenges SET status = 'completed',
                 opponent_id = %s, opponent_car_id = %s, winner_id = %s, completed_at = %s
                 WHERE id = %s''',
              (user_id, my_car_id, winner_id, datetime.now().isoformat(), challenge_id))
    conn.commit(); c.close(); conn.close()

    log_transaction(author_id, 'race_win' if winner_id == author_id else 'race_lose',
                    bet if winner_id == author_id else -bet, author_car_id,
                    'Гонка: победа' if winner_id == author_id else 'Гонка: поражение')
    log_transaction(user_id, 'race_win' if winner_id == user_id else 'race_lose',
                    bet if winner_id == user_id else -bet, my_car_id,
                    'Гонка: победа' if winner_id == user_id else 'Гонка: поражение')

    for uid in (author_id, user_id):
        if uid == winner_id:
            add_xp(uid, XP_REWARDS.get('race_win', 50))
        else:
            add_xp(uid, XP_REWARDS.get('race_lose', 15))
        progress_quest(uid, 'races_play_5', 1)
        if uid == winner_id:
            progress_quest(uid, 'win_races_3', 1)

    return True, 'Гонка завершена!', {
        'winner_id': winner_id, 'challenge_id': challenge_id, 'car_transferred': car_transferred}


def get_race(challenge_id):
    conn = get_db(); c = conn.cursor()
    c.execute('''SELECT id, user_id, car_id, bet, offer_car, hide_car, status,
                        opponent_id, opponent_car_id, winner_id, created_at, completed_at
                 FROM race_challenges WHERE id = %s''', (challenge_id,))
    row = c.fetchone(); c.close(); conn.close()
    if not row: return None
    return {
        'id': row[0], 'user_id': row[1], 'car_id': row[2], 'bet': row[3],
        'offer_car': row[4], 'hide_car': bool(row[5]), 'status': row[6],
        'opponent_id': row[7], 'opponent_car_id': row[8], 'winner_id': row[9],
        'created_at': row[10], 'completed_at': row[11],
        'author': get_username_by_id(row[1]),
        'author_car': get_car_full(row[2]),
        'opponent': get_username_by_id(row[7]) if row[7] else None,
        'opponent_car': get_car_full(row[8]) if row[8] else None,
    }


def count_active_challenges():
    cleanup_expired_challenges()
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM race_challenges WHERE status = 'open'")
    r = c.fetchone(); c.close(); conn.close()
    return r[0] if r else 0


# ---------- РЕЙТИНГ ----------
def get_leaderboard(sort_by='cars', limit=50):
    admin_list = list(ADMIN_USERNAMES) or ['']
    conn = get_db(); c = conn.cursor()
    if sort_by == 'balance':
        c.execute('''SELECT u.id, u.username, COALESCE(u.balance, 0) as val,
                     (u.avatar_data IS NOT NULL), COALESCE(u.level, 1)
                     FROM users u
                     WHERE u.username != ALL(%s)
                     ORDER BY val DESC, u.id ASC LIMIT %s''', (admin_list, limit))
    elif sort_by == 'races':
        c.execute('''SELECT u.id, u.username,
                     (SELECT COUNT(*) FROM transactions t WHERE t.user_id = u.id AND t.type = 'race_win') as val,
                     (u.avatar_data IS NOT NULL), COALESCE(u.level, 1)
                     FROM users u
                     WHERE u.username != ALL(%s)
                     ORDER BY val DESC, u.id ASC LIMIT %s''', (admin_list, limit))
    elif sort_by == 'achievements':
        c.execute('''SELECT u.id, u.username,
                     (SELECT COUNT(*) FROM user_achievements ua WHERE ua.user_id = u.id) as val,
                     (u.avatar_data IS NOT NULL), COALESCE(u.level, 1)
                     FROM users u
                     WHERE u.username != ALL(%s)
                     ORDER BY val DESC, u.id ASC LIMIT %s''', (admin_list, limit))
    elif sort_by == 'level':
        c.execute('''SELECT u.id, u.username, COALESCE(u.level, 1) as val,
                     (u.avatar_data IS NOT NULL), COALESCE(u.level, 1)
                     FROM users u
                     WHERE u.username != ALL(%s)
                     ORDER BY val DESC, u.xp DESC, u.id ASC LIMIT %s''', (admin_list, limit))
    elif sort_by == 'collections':
        c.execute('''SELECT u.id, u.username,
                     (SELECT COUNT(*) FROM user_collections uc WHERE uc.user_id = u.id AND uc.main_claimed = TRUE) as val,
                     (u.avatar_data IS NOT NULL), COALESCE(u.level, 1)
                     FROM users u
                     WHERE u.username != ALL(%s)
                     ORDER BY val DESC, u.id ASC LIMIT %s''', (admin_list, limit))
    else:
        c.execute('''SELECT u.id, u.username,
                     (SELECT COUNT(*) FROM user_cars uc WHERE uc.user_id = u.id) as val,
                     (u.avatar_data IS NOT NULL), COALESCE(u.level, 1)
                     FROM users u
                     WHERE u.username != ALL(%s)
                     ORDER BY val DESC, u.id ASC LIMIT %s''', (admin_list, limit))
    rows = c.fetchall(); c.close(); conn.close()
    result = []
    for i, row in enumerate(rows, start=1):
        result.append({'rank': i, 'id': row[0], 'username': row[1],
                       'value': row[2] or 0, 'has_avatar': row[3], 'level': row[4]})
    return result

# ---------- ПУБЛИЧНЫЙ ГАРАЖ ----------
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


@app.context_processor
def inject_appearance():
    if 'user_id' in session:
        try:
            return {'appearance': get_user_appearance(session['user_id'])}
        except Exception:
            pass
    return {'appearance': {'sound': True, 'music': False, 'vibration': True, 'dark': False}}


# ================= МАРШРУТЫ =================
@app.route('/')
def index():
    profile = None; favorite_car = None; cars_count = 0
    bonus_ready = False; bonus_left = ''
    spin_ready = False; spin_left = ''
    achievements_count = 0
    incoming_trades_count = 0
    active_races_count = 0
    wishlist_count = 0
    friends_count = 0
    incoming_friend_requests = 0
    streak = 0; next_bonus = 0
    level_info = {'level': 1, 'xp': 0, 'xp_needed': 100, 'progress': 0}
    quests_unclaimed = 0
    collections_ready = 0
    collections_total = 0
    if 'user_id' in session:
        flash_new_achievements(session['user_id'])
        profile = get_user_profile(session['user_id'])
        if profile:
            level_info = {'level': profile['level'], 'xp': profile['xp'],
                          'xp_needed': profile['xp_needed'],
                          'progress': min(100, int(profile['xp'] * 100 / profile['xp_needed'])) if profile['xp_needed'] else 0}
        if profile and profile['favorite_car_id']:
            favorite_car = get_car_info(profile['favorite_car_id'])
        cars_count = count_user_cars(session['user_id'])
        bonus_ready, secs = can_claim_bonus(session['user_id'])
        if not bonus_ready: bonus_left = format_time_left(secs)
        streak, next_bonus = get_bonus_preview(session['user_id'])
        spin_ready, secs2 = can_spin(session['user_id'])
        if not spin_ready: spin_left = format_time_left(secs2)
        achievements_count = len(get_unlocked_keys(session['user_id']))
        incoming_trades_count = count_incoming_trades(session['user_id'])
        active_races_count = count_active_challenges()
        wishlist_count = len(get_wishlist_ids(session['user_id']))
        friends_count = count_friends(session['user_id'])
        incoming_friend_requests = count_incoming_requests(session['user_id'])
        try:
            quests, all_done, bonus_claimed = get_user_quests(session['user_id'])
            quests_unclaimed = sum(1 for q in quests if q['completed'] and not q['claimed'])
        except Exception:
            quests_unclaimed = 0
        try:
            all_cols = get_all_collections_for_user(session['user_id'])
            collections_total = len(all_cols)
            for col in all_cols:
                p = col['progress']
                if p['completed'] and not p['main_claimed']:
                    collections_ready += 1
                elif p['main_claimed'] and p['bonus_available']:
                    collections_ready += len(p['bonus_available'])
        except Exception:
            pass
    return render_template('index.html',
                           user=session.get('username'), profile=profile,
                           favorite_car=favorite_car, cars_count=cars_count,
                           bonus_ready=bonus_ready, bonus_left=bonus_left,
                           spin_ready=spin_ready, spin_left=spin_left,
                           achievements_count=achievements_count,
                           total_achievements=len(ACHIEVEMENTS),
                           incoming_trades_count=incoming_trades_count,
                           active_races_count=active_races_count,
                           wishlist_count=wishlist_count,
                           friends_count=friends_count,
                           incoming_friend_requests=incoming_friend_requests,
                           streak=streak, next_bonus=next_bonus,
                           level_info=level_info,
                           quests_unclaimed=quests_unclaimed,
                           collections_ready=collections_ready,
                           collections_total=collections_total,
                           is_admin=is_admin(session.get('username')))


@app.route('/bonus', methods=['POST'])
@login_required
def bonus():
    ready, _ = can_claim_bonus(session['user_id'])
    if ready:
        amount, streak = claim_bonus(session['user_id'])
        flash(f'🎁 Бонус получен: +{amount} монет (серия {streak})!')
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


# ---------- ВНЕШНИЙ ВИД ----------
@app.route('/appearance', methods=['GET', 'POST'])
@login_required
def appearance_page():
    user_id = session['user_id']
    if request.method == 'POST':
        sound = bool(request.form.get('sound'))
        music = bool(request.form.get('music'))
        vibration = bool(request.form.get('vibration'))
        dark = bool(request.form.get('dark'))
        update_user_appearance(user_id, sound, music, vibration, dark)
        flash('Настройки сохранены!')
        return redirect(url_for('appearance_page'))
    app_settings = get_user_appearance(user_id)
    return render_template('appearance.html', settings=app_settings,
                           user=session.get('username'),
                           is_admin=is_admin(session.get('username')))


# ---------- КОЛЛЕКЦИИ ----------
@app.route('/collections')
@login_required
def collections_page():
    flash_new_achievements(session['user_id'])
    cols = get_all_collections_for_user(session['user_id'])
    completed = sum(1 for c in cols if c['progress']['completed'])
    claimed = sum(1 for c in cols if c['progress']['main_claimed'])
    return render_template('collections.html', collections=cols,
                           completed=completed, claimed=claimed, total=len(cols),
                           user=session.get('username'),
                           is_admin=is_admin(session.get('username')))


@app.route('/collections/<int:cid>')
@login_required
def collection_view(cid):
    col = get_collection(cid)
    if not col:
        flash('Коллекция не найдена'); return redirect(url_for('collections_page'))
    cars = get_collection_cars(cid)
    prog = get_collection_progress(session['user_id'], cid)
    excl_car = get_car_full(col['exclusive_car_id']) if col['exclusive_car_id'] else None
    rarity_info = COLLECTION_RARITY.get(col['rarity'], COLLECTION_RARITY['common'])
    return render_template('collection_view.html', col=col, cars=cars, prog=prog,
                           excl_car=excl_car, rarity_info=rarity_info,
                           user=session.get('username'),
                           is_admin=is_admin(session.get('username')))


@app.route('/collections/<int:cid>/claim', methods=['POST'])
@login_required
def collection_claim(cid):
    ok, msg = claim_collection_reward(session['user_id'], cid)
    flash(msg)
    return redirect(url_for('collection_view', cid=cid))


@app.route('/collections/<int:cid>/bonus/<int:car_id>', methods=['POST'])
@login_required
def collection_bonus_claim(cid, car_id):
    ok, msg = claim_collection_bonus(session['user_id'], cid, car_id)
    flash(msg)
    return redirect(url_for('collection_view', cid=cid))


# ---------- BULK UPLOAD ----------
@app.route('/admin/bulk_upload')
@admin_required
def admin_bulk_upload():
    return render_template('admin_bulk_upload.html', user=session.get('username'), is_admin=True)


@app.route('/admin/bulk_upload/process', methods=['POST'])
@admin_required
def admin_bulk_upload_process():
    import traceback
    try:
        csv_file = request.files.get('csv_file')
        zip_file = request.files.get('zip_file')
        skip_existing = bool(request.form.get('skip_existing'))
        dry_run = bool(request.form.get('dry_run'))

        if not csv_file or csv_file.filename == '':
            flash('Не выбран CSV-файл'); return redirect(url_for('admin_bulk_upload'))
        if not zip_file or zip_file.filename == '':
            flash('Не выбран ZIP-файл'); return redirect(url_for('admin_bulk_upload'))

        csv_bytes = csv_file.read()
        zip_bytes = zip_file.read()
        rows, errors, headers = parse_bulk_csv(csv_bytes)
        if not rows and errors:
            return render_template('admin_bulk_upload.html',
                                   user=session.get('username'), is_admin=True,
                                   fatal_errors=errors, headers=headers,
                                   csv_name=csv_file.filename, zip_name=zip_file.filename)
        images, zip_err = extract_zip_images(zip_bytes)
        if zip_err:
            flash(zip_err); return redirect(url_for('admin_bulk_upload'))

        if dry_run:
            conn = get_db(); c = conn.cursor()
            c.execute('SELECT LOWER(model) FROM cars')
            existing = {r[0] for r in c.fetchall()}
            c.close(); conn.close()
            will_add = 0; will_skip_dup = 0; will_skip_img = []
            for row in rows:
                if skip_existing and row['model'].lower() in existing:
                    will_skip_dup += 1; continue
                if row['image_filename'].lower() not in images:
                    will_skip_img.append(row); continue
                will_add += 1
            return render_template('admin_bulk_upload.html',
                                   user=session.get('username'), is_admin=True,
                                   preview=True, total_rows=len(rows), will_add=will_add,
                                   will_skip_dup=will_skip_dup,
                                   will_skip_img=will_skip_img[:30],
                                   will_skip_img_count=len(will_skip_img),
                                   parse_errors=errors,
                                   csv_name=csv_file.filename, zip_name=zip_file.filename,
                                   images_count=len(images))

        result = bulk_insert_cars(rows, images, skip_existing=skip_existing)
        return render_template('admin_bulk_upload.html',
                               user=session.get('username'), is_admin=True,
                               result=result, parse_errors=errors,
                               csv_name=csv_file.filename, zip_name=zip_file.filename)
    except Exception:
        return '<h2 style="color:red;">Ошибка:</h2><pre style="font-size:13px;padding:20px;background:#fff0f0;white-space:pre-wrap;">' + traceback.format_exc() + '</pre>', 500


@app.route('/admin/bulk_upload/template.csv')
@admin_required
def admin_bulk_template():
    csv_content = (
        "model,brand,rating,price,horsepower,acceleration,top_speed,image_filename,is_exclusive\n"
        "BMW M3 E46,BMW,5,5000,343,5.1,250,bmw_m3_e46.png,0\n"
    )
    resp = make_response(csv_content)
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = 'attachment; filename=autokards_template.csv'
    return resp


# ---------- АДМИН: КОЛЛЕКЦИИ ----------
@app.route('/admin/collections')
@admin_required
def admin_collections():
    cols = get_collections()
    for col in cols:
        col['car_count'] = len(get_collection_cars(col['id']))
        col['rarity_info'] = COLLECTION_RARITY.get(col['rarity'], COLLECTION_RARITY['common'])
    return render_template('admin_collections.html', collections=cols,
                           rarities=COLLECTION_RARITY,
                           user=session.get('username'), is_admin=True)


@app.route('/admin/collections/new', methods=['GET', 'POST'])
@admin_required
def admin_collection_new():
    all_cars = get_catalog()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()[:80]
        description = request.form.get('description', '').strip()[:500]
        rarity = request.form.get('rarity', 'common')
        if rarity not in COLLECTION_RARITY: rarity = 'common'
        try: coins_reward = int(request.form.get('coins_reward', '500'))
        except ValueError: coins_reward = 500
        try: bonus_coins = int(request.form.get('bonus_coins', '50'))
        except ValueError: bonus_coins = 50
        excl_raw = request.form.get('exclusive_car_id', '').strip()
        exclusive_car_id = int(excl_raw) if excl_raw.isdigit() else None
        car_ids = [int(x) for x in request.form.getlist('car_ids') if x.isdigit()]
        if not name:
            flash('Впиши название'); return redirect(url_for('admin_collection_new'))
        if not car_ids:
            flash('Выбери хотя бы одну машину'); return redirect(url_for('admin_collection_new'))
        cid = create_collection(name, description, rarity, coins_reward, bonus_coins, exclusive_car_id, car_ids)
        flash(f'Коллекция «{name}» создана!')
        return redirect(url_for('admin_collection_view', cid=cid))
    return render_template('admin_collection_form.html', mode='new',
                           all_cars=all_cars, col=None, col_car_ids=set(),
                           rarities=COLLECTION_RARITY,
                           user=session.get('username'), is_admin=True)


@app.route('/admin/collections/<int:cid>/edit', methods=['GET', 'POST'])
@admin_required
def admin_collection_edit(cid):
    col = get_collection(cid)
    if not col:
        flash('Не найдено'); return redirect(url_for('admin_collections'))
    all_cars = get_catalog()
    car_ids_in = {c['id'] for c in get_collection_cars(cid)}
    if request.method == 'POST':
        name = request.form.get('name', '').strip()[:80]
        description = request.form.get('description', '').strip()[:500]
        rarity = request.form.get('rarity', 'common')
        if rarity not in COLLECTION_RARITY: rarity = 'common'
        try: coins_reward = int(request.form.get('coins_reward', '500'))
        except ValueError: coins_reward = 500
        try: bonus_coins = int(request.form.get('bonus_coins', '50'))
        except ValueError: bonus_coins = 50
        excl_raw = request.form.get('exclusive_car_id', '').strip()
        exclusive_car_id = int(excl_raw) if excl_raw.isdigit() else None
        car_ids = [int(x) for x in request.form.getlist('car_ids') if x.isdigit()]
        if not name:
            flash('Впиши название'); return redirect(url_for('admin_collection_edit', cid=cid))
        if not car_ids:
            flash('Выбери хотя бы одну машину'); return redirect(url_for('admin_collection_edit', cid=cid))
        update_collection(cid, name, description, rarity, coins_reward, bonus_coins, exclusive_car_id, car_ids)
        flash('Коллекция обновлена!')
        return redirect(url_for('admin_collection_view', cid=cid))
    return render_template('admin_collection_form.html', mode='edit',
                           all_cars=all_cars, col=col, col_car_ids=car_ids_in,
                           rarities=COLLECTION_RARITY,
                           user=session.get('username'), is_admin=True)


@app.route('/admin/collections/<int:cid>')
@admin_required
def admin_collection_view(cid):
    col = get_collection(cid)
    if not col:
        flash('Не найдено'); return redirect(url_for('admin_collections'))
    cars = get_collection_cars(cid)
    excl_car = get_car_full(col['exclusive_car_id']) if col['exclusive_car_id'] else None
    rarity_info = COLLECTION_RARITY.get(col['rarity'], COLLECTION_RARITY['common'])
    return render_template('admin_collection_view.html', col=col, cars=cars,
                           excl_car=excl_car, rarity_info=rarity_info,
                           user=session.get('username'), is_admin=True)


@app.route('/admin/collections/<int:cid>/delete', methods=['POST'])
@admin_required
def admin_collection_delete(cid):
    delete_collection(cid)
    flash('Коллекция удалена')
    return redirect(url_for('admin_collections'))


# ---------- ЗАДАНИЯ ----------
@app.route('/quests')
@login_required
def quests_page():
    flash_new_achievements(session['user_id'])
    quests, all_done, bonus_claimed = get_user_quests(session['user_id'])
    level_info = get_user_level_info(session['user_id'])
    completed_total = count_completed_quests(session['user_id'])
    return render_template('quests.html', quests=quests, all_done=all_done,
                           bonus_claimed=bonus_claimed, level_info=level_info,
                           completed_total=completed_total,
                           bonus_xp=QUEST_BONUS_XP, bonus_coins=QUEST_BONUS_COINS,
                           user=session.get('username'),
                           is_admin=is_admin(session.get('username')))


@app.route('/quests/claim/<quest_key>', methods=['POST'])
@login_required
def quest_claim(quest_key):
    ok, msg = claim_quest(session['user_id'], quest_key)
    flash(msg)
    return redirect(url_for('quests_page'))


@app.route('/quests/claim_bonus', methods=['POST'])
@login_required
def quest_claim_bonus():
    ok, msg = claim_quest_bonus(session['user_id'])
    flash(msg)
    return redirect(url_for('quests_page'))


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
                    flash('Аватарка: только PNG, JPG, WEBP, GIF'); return redirect(url_for('settings'))
            public_ids = [int(x) for x in request.form.getlist('public_cars') if x.isdigit()]
            my_ids = {c[0] for c in get_user_cars(user_id)}
            public_ids = [x for x in public_ids if x in my_ids]
            set_public_cars(user_id, public_ids)
            update_profile(user_id, bio, fav_id)
            flash('Профиль обновлён!')
            return redirect(url_for('index'))
        profile = get_user_profile(user_id)
        return render_template('settings.html', user=session.get('username'), profile=profile,
                               my_cars=get_user_cars(user_id), public_ids=get_public_ids(user_id),
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
            flash('Игрока нет'); return redirect(url_for('index'))
        profile = get_user_profile(user_row[0])
        favorite_car = get_car_info(profile['favorite_car_id']) if profile['favorite_car_id'] else None
        fstatus = None
        if 'user_id' in session and session['user_id'] != user_row[0]:
            fstatus = get_friend_status(session['user_id'], user_row[0])
        incoming_req_id = None
        if fstatus == 'pending_in':
            for r in get_incoming_requests(session['user_id']):
                if r['user_id'] == user_row[0]:
                    incoming_req_id = r['id']; break
        return render_template('profile.html', profile=profile, favorite_car=favorite_car,
                               public_cars=get_public_cars(user_row[0]),
                               cars_count=count_user_cars(user_row[0]),
                               friends_count=count_friends(user_row[0]),
                               achievements=get_achievements_for_user(user_row[0]),
                               friend_status=fstatus, incoming_req_id=incoming_req_id,
                               user=session.get('username'),
                               is_admin=is_admin(session.get('username')))
    except Exception:
        return '<h2 style="color:red;">Ошибка в /profile:</h2><pre style="font-size:14px;padding:20px;background:#fff0f0;white-space:pre-wrap;">' + traceback.format_exc() + '</pre>', 500


# ---------- ДРУЗЬЯ ----------
@app.route('/friends')
@login_required
def friends_page():
    user_id = session['user_id']
    friends = get_friends(user_id)
    incoming = get_incoming_requests(user_id)
    outgoing = get_outgoing_requests(user_id)
    search_query = request.args.get('q', '').strip()
    search_results = []
    if search_query:
        search_results = search_users(search_query, user_id)
        for r in search_results:
            r['status'] = get_friend_status(user_id, r['id'])
    return render_template('friends.html', friends=friends, incoming=incoming, outgoing=outgoing,
                           search_query=search_query, search_results=search_results,
                           user=session.get('username'),
                           is_admin=is_admin(session.get('username')))


@app.route('/friends/request', methods=['POST'])
@login_required
def friends_request():
    username = request.form.get('username', '').strip()
    if not username:
        flash('Впиши ник игрока'); return redirect(url_for('friends_page'))
    ok, msg = send_friend_request(session['user_id'], username)
    flash(msg)
    return redirect(request.referrer or url_for('friends_page'))


@app.route('/friends/accept/<int:req_id>', methods=['POST'])
@login_required
def friends_accept(req_id):
    ok, msg = accept_friend_request(req_id, session['user_id'])
    flash(msg)
    return redirect(url_for('friends_page'))


@app.route('/friends/reject/<int:req_id>', methods=['POST'])
@login_required
def friends_reject(req_id):
    ok, msg = reject_friend_request(req_id, session['user_id'])
    flash(msg)
    return redirect(url_for('friends_page'))


@app.route('/friends/cancel/<int:req_id>', methods=['POST'])
@login_required
def friends_cancel(req_id):
    ok, msg = cancel_friend_request(req_id, session['user_id'])
    flash(msg)
    return redirect(url_for('friends_page'))


@app.route('/friends/remove/<int:friend_id>', methods=['POST'])
@login_required
def friends_remove(friend_id):
    ok, msg = remove_friend(session['user_id'], friend_id)
    flash(msg)
    return redirect(url_for('friends_page'))


# ---------- ГАРАЖ ----------
@app.route('/garage')
@login_required
def garage():
    flash_new_achievements(session['user_id'])
    filter_type = request.args.get('filter', 'all')
    cars = get_user_cars(session['user_id'])
    fav_ids = get_favorite_ids(session['user_id'])
    if filter_type == 'fav':
        cars = [c for c in cars if c[0] in fav_ids]
    return render_template('garage.html', cars=cars, balance=get_balance(session['user_id']),
                           fav_ids=fav_ids, filter=filter_type,
                           total_count=count_user_cars(session['user_id']),
                           user=session.get('username'),
                           is_admin=is_admin(session.get('username')))


@app.route('/garage/remove/<int:car_id>', methods=['POST'])
@login_required
def remove_from_garage(car_id):
    _, msg, _ = sell_car(session['user_id'], car_id)
    flash(msg)
    return redirect(url_for('garage'))


@app.route('/garage/favorite/<int:car_id>', methods=['POST'])
@login_required
def garage_favorite(car_id):
    if not has_car(session['user_id'], car_id):
        flash('У тебя нет этой машины'); return redirect(url_for('garage'))
    added = toggle_favorite(session['user_id'], car_id)
    flash('⭐ Добавлено в избранное' if added else 'Убрано из избранного')
    return redirect(request.referrer or url_for('garage'))


# ---------- МАГАЗИН ----------
@app.route('/shop')
@login_required
def shop():
    import traceback
    try:
        ensure_discount()
        discount = get_active_discount()
        balance = get_balance(session['user_id'])
        settings = {k: get_setting(k) for k in DEFAULT_SETTINGS}
        sort = request.args.get('sort', 'new')
        search_query = request.args.get('q', '').strip()
        brand_filter = request.args.get('brand', '').strip()
        price_min = request.args.get('price_min', '').strip()
        price_max = request.args.get('price_max', '').strip()
        wish_ids = get_wishlist_ids(session['user_id'])
        user_level = get_user_level_info(session['user_id'])['level']

        conn = get_db(); c = conn.cursor()
        c.execute('SELECT id, model, rating, price, horsepower, brand, COALESCE(is_exclusive, FALSE) '
                  'FROM cars WHERE COALESCE(is_exclusive, FALSE) = FALSE ORDER BY id DESC')
        rows = c.fetchall(); c.close(); conn.close()

        all_brands = get_all_brands()

        try: pmin = int(price_min) if price_min else None
        except ValueError: pmin = None
        try: pmax = int(price_max) if price_max else None
        except ValueError: pmax = None

        cars = []
        for row in rows:
            cid, model, rating, price, hp, brand, excl = row
            price = price or 0
            if search_query and search_query.lower() not in model.lower(): continue
            if brand_filter and (brand or '').lower() != brand_filter.lower(): continue
            if pmin is not None and price < pmin: continue
            if pmax is not None and price > pmax: continue

            final_price = price
            has_disc = False
            if discount and discount['car_id'] == cid:
                final_price = int(price * (100 - discount['discount_percent']) / 100)
                has_disc = True
            req_level = get_level_required_for_stars(rating)
            locked = user_level < req_level
            cars.append({'id': cid, 'model': model, 'rating': rating, 'price': price,
                         'final_price': final_price, 'has_discount': has_disc,
                         'horsepower': hp or 0, 'brand': brand or '',
                         'owned': has_car(session['user_id'], cid),
                         'wished': cid in wish_ids,
                         'locked': locked, 'req_level': req_level})

        if sort == 'price_asc': cars.sort(key=lambda x: x['final_price'])
        elif sort == 'price_desc': cars.sort(key=lambda x: x['final_price'], reverse=True)
        elif sort == 'rating_desc': cars.sort(key=lambda x: x['rating'], reverse=True)
        elif sort == 'rating_asc': cars.sort(key=lambda x: x['rating'])
        elif sort == 'hp_desc': cars.sort(key=lambda x: x['horsepower'], reverse=True)

        query_parts = []
        if search_query: query_parts.append(f'q={search_query}')
        if brand_filter: query_parts.append(f'brand={brand_filter}')
        if price_min: query_parts.append(f'price_min={price_min}')
        if price_max: query_parts.append(f'price_max={price_max}')
        query_keep = ('&'.join(query_parts) + '&') if query_parts else ''

        return render_template('shop.html', cars=cars, balance=balance, discount=discount,
                               settings=settings, sort=sort, user_level=user_level,
                               wishlist_count=len(wish_ids),
                               all_brands=all_brands,
                               search_query=search_query,
                               brand_filter=brand_filter,
                               price_min=price_min,
                               price_max=price_max,
                               total_count=len(rows),
                               query_keep=query_keep,
                               user=session.get('username'),
                               is_admin=is_admin(session.get('username')))
    except Exception:
        return '<h2 style="color:red;">Ошибка в /shop:</h2><pre style="font-size:14px;padding:20px;background:#fff0f0;white-space:pre-wrap;">' + traceback.format_exc() + '</pre>', 500


@app.route('/shop/buy/<int:car_id>', methods=['POST'])
@login_required
def shop_buy(car_id):
    _, msg = buy_car(session['user_id'], car_id)
    flash(msg)
    return redirect(url_for('shop'))


@app.route('/shop/wishlist/<int:car_id>', methods=['POST'])
@login_required
def shop_wishlist_toggle(car_id):
    added = toggle_wishlist(session['user_id'], car_id)
    flash('❤ Добавлено в желаемое' if added else 'Убрано из желаемого')
    return redirect(request.referrer or url_for('shop'))


@app.route('/shop/wishlist')
@login_required
def wishlist_page():
    items = get_wishlist_cars(session['user_id'])
    balance = get_balance(session['user_id'])
    ensure_discount()
    discount = get_active_discount()
    user_level = get_user_level_info(session['user_id'])['level']
    for item in items:
        final_price = item['price']
        item['has_discount'] = False
        if discount and discount['car_id'] == item['id']:
            final_price = int(item['price'] * (100 - discount['discount_percent']) / 100)
            item['has_discount'] = True
        item['final_price'] = final_price
        item['owned'] = has_car(session['user_id'], item['id'])
        item['req_level'] = get_level_required_for_stars(item['rating'])
        item['locked'] = user_level < item['req_level']
    return render_template('wishlist.html', items=items, balance=balance,
                           user=session.get('username'),
                           is_admin=is_admin(session.get('username')))


@app.route('/shop/add', methods=['GET', 'POST'])
@admin_required
def add_car_page():
    if request.method == 'POST':
        model = request.form.get('model', '').strip()
        brand = request.form.get('brand', '').strip()[:40]
        rating = request.form.get('rating', '3')
        price = request.form.get('price', '500')
        hp = request.form.get('horsepower', '').strip()
        accel = request.form.get('acceleration', '').strip()
        top = request.form.get('top_speed', '').strip()
        is_exclusive = bool(request.form.get('is_exclusive'))
        file = request.files.get('image')
        if not model: flash('Впиши название'); return redirect(url_for('add_car_page'))
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
        try: accel = float(accel) if accel else None
        except ValueError: accel = None
        if not file or file.filename == '': flash('Выбери картинку'); return redirect(url_for('add_car_page'))
        if file.mimetype not in ALLOWED_MIME: flash('Формат PNG/JPG/WEBP/GIF'); return redirect(url_for('add_car_page'))
        add_car(model, brand, rating, price, hp, accel, top, is_exclusive, file.read(), file.mimetype)
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
        brand = request.form.get('brand', '').strip()[:40]
        rating = request.form.get('rating', '3')
        price = request.form.get('price', '500')
        hp = request.form.get('horsepower', '').strip()
        accel = request.form.get('acceleration', '').strip()
        top = request.form.get('top_speed', '').strip()
        is_exclusive = bool(request.form.get('is_exclusive'))
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
        try: accel = float(accel) if accel else None
        except ValueError: accel = None
        update_car(car_id, model, brand, rating, price, hp, accel, top, is_exclusive)
        flash('Машина обновлена')
        return redirect(url_for('shop'))
    return render_template('edit_car.html', car=car, user=session.get('username'), is_admin=True)


@app.route('/shop/delete/<int:car_id>', methods=['POST'])
@admin_required
def delete_from_catalog(car_id):
    delete_car_from_catalog(car_id)
    flash('Удалено')
    return redirect(url_for('shop'))


# ---------- КАРТОЧКА МАШИНЫ ----------
@app.route('/car/<int:car_id>')
def car_detail(car_id):
    car = get_car_full(car_id)
    if not car:
        flash('Машина не найдена'); return redirect(url_for('index'))
    owned = False
    if 'user_id' in session:
        owned = has_car(session['user_id'], car_id)
    req_level = get_level_required_for_stars(car['rating'])
    user_level = get_user_level_info(session['user_id'])['level'] if 'user_id' in session else 1
    locked = user_level < req_level
    return render_template('car_detail.html', car=car, owned=owned,
                           req_level=req_level, locked=locked, user_level=user_level,
                           user=session.get('username'),
                           is_admin=is_admin(session.get('username')))


# ---------- СРАВНЕНИЕ ----------
@app.route('/compare')
@login_required
def compare_page():
    all_cars = get_catalog()
    c1 = request.args.get('c1', '')
    c2 = request.args.get('c2', '')
    car1 = get_car_full(int(c1)) if c1.isdigit() else None
    car2 = get_car_full(int(c2)) if c2.isdigit() else None
    return render_template('compare.html', all_cars=all_cars, car1=car1, car2=car2,
                           user=session.get('username'),
                           is_admin=is_admin(session.get('username')))


# ---------- КОЛЕСО ----------
@app.route('/wheel')
@login_required
def wheel():
    flash_new_achievements(session['user_id'])
    ready, secs = can_spin(session['user_id'])
    result = session.pop('wheel_result', None)
    paid_enabled = get_setting('paid_wheel_enabled') == '1'
    paid_price = get_int_setting('paid_wheel_price', 1000)
    paid_info = {'car_chance': get_int_setting('paid_wheel_car_chance', 15),
                 'coin_min': get_int_setting('paid_wheel_coin_min', 100),
                 'coin_max': get_int_setting('paid_wheel_coin_max', 600),
                 'car_min_rating': get_int_setting('paid_wheel_car_min_rating', 5),
                 'car_max_rating': get_int_setting('paid_wheel_car_max_rating', 8)}
    free_info = {'car_chance': get_int_setting('wheel_car_chance', 5),
                 'coin_min': get_int_setting('wheel_coin_min', 30),
                 'coin_max': get_int_setting('wheel_coin_max', 150),
                 'car_min_rating': get_int_setting('wheel_car_min_rating', 1),
                 'car_max_rating': get_int_setting('wheel_car_max_rating', 4)}
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
    total_reward = sum(a['reward'] for a in achievements)
    earned_reward = sum(a['reward'] for a in achievements if a['unlocked'])
    return render_template('achievements.html', achievements=achievements,
                           unlocked_count=unlocked, total=len(achievements),
                           total_reward=total_reward, earned_reward=earned_reward,
                           user=session.get('username'),
                           is_admin=is_admin(session.get('username')))


# ---------- ОБМЕНЫ ----------
@app.route('/trades')
@login_required
def trades_page():
    incoming = get_incoming_trades(session['user_id'])
    outgoing = [t for t in get_outgoing_trades(session['user_id']) if t['status'] == 'pending']
    history = get_trade_history(session['user_id'])
    return render_template('trades.html', incoming=incoming, outgoing=outgoing, history=history,
                           balance=get_balance(session['user_id']),
                           my_id=session['user_id'],
                           user=session.get('username'),
                           is_admin=is_admin(session.get('username')))


@app.route('/trades/new', methods=['GET', 'POST'])
@login_required
def trade_new():
    if request.method == 'POST':
        to_username = request.form.get('to_username', '').strip()
        from_car_id = request.form.get('from_car_id', '')
        from_coins = request.form.get('from_coins', '0')
        message = request.form.get('message', '').strip()
        if not to_username: flash('Впиши ник игрока'); return redirect(url_for('trade_new'))
        if not from_car_id.isdigit(): flash('Выбери свою машину'); return redirect(url_for('trade_new'))
        try: from_coins = int(from_coins or 0)
        except ValueError: flash('Монеты должны быть числом'); return redirect(url_for('trade_new'))
        ok, result = create_trade(session['user_id'], to_username, int(from_car_id), from_coins, message)
        if ok:
            flash('Предложение отправлено!')
            return redirect(url_for('trades_page'))
        flash(result); return redirect(url_for('trade_new'))
    to_prefill = request.args.get('to', '')
    friends = get_friends(session['user_id'])
    return render_template('trade_new.html', my_cars=get_user_cars(session['user_id']),
                           balance=get_balance(session['user_id']),
                           to_prefill=to_prefill, friends=friends,
                           user=session.get('username'),
                           is_admin=is_admin(session.get('username')))


@app.route('/trades/<int:trade_id>')
@login_required
def trade_view(trade_id):
    t = get_trade_full(trade_id)
    if not t: flash('Обмен не найден'); return redirect(url_for('trades_page'))
    if t['from_user_id'] != session['user_id'] and t['to_user_id'] != session['user_id']:
        flash('Это не твой обмен'); return redirect(url_for('trades_page'))
    my_cars = get_user_cars(session['user_id']) if t['to_user_id'] == session['user_id'] else []
    return render_template('trade_view.html', trade=t, my_cars=my_cars,
                           balance=get_balance(session['user_id']),
                           my_id=session['user_id'],
                           user=session.get('username'),
                           is_admin=is_admin(session.get('username')))


@app.route('/trades/<int:trade_id>/accept', methods=['POST'])
@login_required
def trade_accept(trade_id):
    to_car_raw = request.form.get('to_car_id', '').strip()
    to_coins = request.form.get('to_coins', '0')
    to_car_id = int(to_car_raw) if to_car_raw.isdigit() else None
    try: to_coins = int(to_coins or 0)
    except ValueError:
        flash('Монеты должны быть числом'); return redirect(url_for('trade_view', trade_id=trade_id))
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


# ---------- ГОНКИ ----------
@app.route('/races')
@login_required
def races_page():
    my_challenges = get_user_challenges(session['user_id'])
    other_challenges = get_open_challenges(exclude_user_id=session['user_id'])
    return render_template('races.html', my_challenges=my_challenges,
                           other_challenges=other_challenges,
                           my_cars=get_user_cars(session['user_id']),
                           balance=get_balance(session['user_id']),
                           user=session.get('username'),
                           is_admin=is_admin(session.get('username')))


@app.route('/races/create', methods=['POST'])
@login_required
def race_create():
    car_id = request.form.get('car_id', '')
    bet = request.form.get('bet', '0')
    offer_car = bool(request.form.get('offer_car'))
    hide_car = bool(request.form.get('hide_car'))
    if not car_id.isdigit(): flash('Выбери машину'); return redirect(url_for('races_page'))
    try:
        bet = int(bet)
        if bet < 0: raise ValueError
    except ValueError:
        flash('Ставка — число'); return redirect(url_for('races_page'))
    ok, result = create_race_challenge(session['user_id'], int(car_id), bet, offer_car, hide_car)
    if ok: flash('Вызов создан! Ждём соперника.')
    else: flash(result)
    return redirect(url_for('races_page'))


@app.route('/races/join/<int:challenge_id>', methods=['POST'])
@login_required
def race_join(challenge_id):
    car_id = request.form.get('car_id', '')
    offer_car = bool(request.form.get('offer_car'))
    if not car_id.isdigit(): flash('Выбери свою машину'); return redirect(url_for('races_page'))
    ok, msg, info = join_race_challenge(challenge_id, session['user_id'], int(car_id), offer_car)
    flash(msg)
    if ok and info:
        return redirect(url_for('race_result', challenge_id=challenge_id))
    return redirect(url_for('races_page'))


@app.route('/races/cancel/<int:challenge_id>', methods=['POST'])
@login_required
def race_cancel(challenge_id):
    ok, msg = cancel_race_challenge(challenge_id, session['user_id'])
    flash(msg)
    return redirect(url_for('races_page'))


@app.route('/races/<int:challenge_id>')
@login_required
def race_result(challenge_id):
    r = get_race(challenge_id)
    if not r: flash('Гонка не найдена'); return redirect(url_for('races_page'))
    if r['user_id'] != session['user_id'] and r['opponent_id'] != session['user_id']:
        flash('Это не твоя гонка'); return redirect(url_for('races_page'))
    winner_id = r['winner_id']
    won = (winner_id == session['user_id']) if winner_id else None
    return render_template('race_result.html', race=r, won=won,
                           user=session.get('username'),
                           is_admin=is_admin(session.get('username')))


# ---------- РЕЙТИНГ ----------
@app.route('/rating')
def rating_page():
    sort = request.args.get('sort', 'cars')
    if sort not in ('cars', 'balance', 'races', 'achievements', 'level', 'collections'):
        sort = 'cars'
    leaders = get_leaderboard(sort_by=sort, limit=50)
    total_users = count_users()
    my_rank = None; my_value = 0
    if 'user_id' in session:
        full_list = get_leaderboard(sort_by=sort, limit=1000)
        for entry in full_list:
            if entry['id'] == session['user_id']:
                my_rank = entry['rank']; my_value = entry['value']; break
    return render_template('rating.html', leaders=leaders, sort=sort,
                           total_users=total_users, my_rank=my_rank, my_value=my_value,
                           my_id=session.get('user_id'),
                           user=session.get('username'),
                           is_admin=is_admin(session.get('username')))


# ---------- АДМИН: ВЫДАЧА ----------
@app.route('/admin/give', methods=['GET', 'POST'])
@admin_required
def admin_give():
    import traceback
    try:
        all_cars = get_catalog()
        user = None
        user_owned = []
        user_achievements = []
        if request.method == 'POST':
            action = request.form.get('action', '')
            username = request.form.get('username', '').strip()
            if action == 'find':
                u = get_user(username)
                if not u:
                    flash(f'Игрок «{username}» не найден')
                else:
                    user = get_user_profile(u[0])
                    user_owned = get_user_cars(u[0])
                    user_achievements = get_unlocked_keys(u[0])
            else:
                u = get_user(username)
                if not u:
                    flash('Игрок не найден'); return redirect(url_for('admin_give'))
                user_id = u[0]
                user = get_user_profile(user_id)
                user_owned = get_user_cars(user_id)
                user_achievements = get_unlocked_keys(user_id)
                if action == 'give_coins':
                    amount = request.form.get('amount', '0')
                    try: amount = int(amount)
                    except ValueError:
                        flash('Сумма должна быть числом'); return redirect(url_for('admin_give'))
                    ok, msg = admin_give_coins(user_id, amount); flash(msg)
                elif action == 'give_car':
                    car_id = request.form.get('car_id', '')
                    if not car_id.isdigit(): flash('Выбери машину'); return redirect(url_for('admin_give'))
                    ok, msg = admin_give_car(user_id, int(car_id)); flash(msg)
                elif action == 'take_car':
                    car_id = request.form.get('car_id', '')
                    if not car_id.isdigit(): flash('Выбери машину'); return redirect(url_for('admin_give'))
                    ok, msg = admin_take_car(user_id, int(car_id)); flash(msg)
                elif action == 'give_ach':
                    key = request.form.get('ach_key', '')
                    ok, msg = admin_give_achievement(user_id, key); flash(msg)
                elif action == 'take_ach':
                    key = request.form.get('ach_key', '')
                    ok, msg = admin_take_achievement(user_id, key); flash(msg)
                elif action == 'set_level':
                    level = request.form.get('level', '1')
                    try: level = int(level)
                    except ValueError:
                        flash('Уровень должен быть числом'); return redirect(url_for('admin_give'))
                    ok, msg = admin_set_level(user_id, level); flash(msg)
                elif action == 'clear_cars':
                    conn = get_db(); c = conn.cursor()
                    c.execute('DELETE FROM user_cars WHERE user_id = %s', (user_id,))
                    c.execute('DELETE FROM public_cars WHERE user_id = %s', (user_id,))
                    c.execute('DELETE FROM favorite_cars WHERE user_id = %s', (user_id,))
                    c.execute('UPDATE users SET favorite_car_id = NULL WHERE id = %s', (user_id,))
                    conn.commit(); c.close(); conn.close()
                    flash('Все машины игрока удалены')
                user = get_user_profile(user_id)
                user_owned = get_user_cars(user_id)
                user_achievements = get_unlocked_keys(user_id)
        return render_template('admin_give.html', user=user, all_cars=all_cars,
                               user_owned=user_owned, user_achievements=user_achievements,
                               all_achievements=ACHIEVEMENTS,
                               current_admin=session.get('username'), is_admin=True)
    except Exception:
        return '<h2 style="color:red;">Ошибка в /admin/give:</h2><pre style="font-size:14px;padding:20px;background:#fff0f0;white-space:pre-wrap;">' + traceback.format_exc() + '</pre>', 500


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
    return render_template('admin_settings.html', settings=settings, discount=discount,
                           discount_car=discount_car,
                           user=session.get('username'), is_admin=True)


@app.route('/admin/discount/reroll', methods=['POST'])
@admin_required
def admin_reroll_discount():
    import traceback
    try:
        conn = get_db(); c = conn.cursor()
        c.execute('DELETE FROM daily_discount'); conn.commit(); c.close(); conn.close()
        r = roll_new_discount()
        if r: flash(f'Новая скидка: «{r["model"]}» — {r["discount_percent"]}%')
        else: flash('Не удалось. Проверь диапазон рейтинга.')
        return redirect(url_for('admin_settings'))
    except Exception:
        return '<h2 style="color:red;">Ошибка:</h2><pre>' + traceback.format_exc() + '</pre>', 500


# ---------- КАРТИНКИ ----------
@app.route('/car_image/<int:car_id>')
def car_image(car_id):
    row = get_car_image(car_id)
    if not row: return '', 404
    return Response(bytes(row[0]), mimetype=row[1])


init_db()

if __name__ == '__main__':
    app.run(debug=True)

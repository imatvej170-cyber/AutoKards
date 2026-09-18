from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)

# Секретный ключ нужен для работы сессий (запоминания пользователя).
# На хостинге задашь свою переменную окружения SECRET_KEY.
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-me-please')

DB_PATH = 'autokards.db'


# ---------- РАБОТА С БАЗОЙ ДАННЫХ ----------
def init_db():
    """Создаёт таблицу пользователей, если её ещё нет."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()


def get_user(username):
    """Ищет пользователя по никнейму. Возвращает строку (id, username, hash) или None."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id, username, password_hash FROM users WHERE username = ?', (username,))
    row = c.fetchone()
    conn.close()
    return row


def create_user(username, password):
    """Создаёт нового пользователя с захешированным паролем."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        'INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)',
        (username, generate_password_hash(password), datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


# ---------- МАРШРУТЫ (СТРАНИЦЫ) ----------
@app.route('/')
def index():
    """Главная страница."""
    return render_template('index.html', user=session.get('username'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    """Регистрация: только никнейм и пароль."""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        password2 = request.form.get('password2', '')

        # Проверки
        if not username or not password:
            flash('Заполни все поля')
            return redirect(url_for('register'))
        if len(username) < 3:
            flash('Никнейм должен быть не короче 3 символов')
            return redirect(url_for('register'))
        if len(username) > 20:
            flash('Никнейм должен быть не длиннее 20 символов')
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

        # Создаём пользователя и сразу логиним его
        create_user(username, password)
        session['username'] = username
        return redirect(url_for('index'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Вход по никнейму и паролю."""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = get_user(username)
        if user and check_password_hash(user[2], password):
            session['username'] = username
            return redirect(url_for('index'))

        flash('Неверный никнейм или пароль')
        return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/logout')
def logout():
    """Выход."""
    session.pop('username', None)
    return redirect(url_for('index'))


# Инициализируем базу при запуске
init_db()

if __name__ == '__main__':
    app.run(debug=True)
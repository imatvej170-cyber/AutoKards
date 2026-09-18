from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
import sqlite3
import os
import uuid
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-me-please')

DB_PATH = 'autokards.db'

UPLOAD_FOLDER = os.path.join('static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ---------- БАЗА ДАННЫХ ----------
def init_db():
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
    c.execute('''
        CREATE TABLE IF NOT EXISTS cars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model TEXT NOT NULL,
            image_filename TEXT NOT NULL,
            rating INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()


def get_user(username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id, username, password_hash FROM users WHERE username = ?', (username,))
    row = c.fetchone()
    conn.close()
    return row


def create_user(username, password):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)',
              (username, generate_password_hash(password), datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_all_cars():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id, model, image_filename, rating FROM cars ORDER BY id DESC')
    rows = c.fetchall()
    conn.close()
    return rows


def add_car(model, image_filename, rating):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT INTO cars (model, image_filename, rating, created_at) VALUES (?, ?, ?, ?)',
              (model, image_filename, rating, datetime.now().isoformat()))
    conn.commit()
    conn.close()


# ---------- ХЕЛПЕРЫ ----------
def is_admin(user_id):
    return user_id == 1


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Сначала войди в аккаунт')
            return redirect(url_for('login'))
        if not is_admin(session['user_id']):
            flash('Доступ только для администратора')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ---------- МАРШРУТЫ ----------
@app.route('/')
def index():
    return render_template('index.html', user=session.get('username'),
                           is_admin=is_admin(session.get('user_id', 0)))


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


@app.route('/garage')
def garage():
    if 'user_id' not in session:
        flash('Сначала войди в аккаунт')
        return redirect(url_for('login'))
    cars = get_all_cars()
    return render_template('garage.html', cars=cars,
                           user=session.get('username'),
                           is_admin=is_admin(session.get('user_id')))


@app.route('/garage/add', methods=['GET', 'POST'])
@admin_required
def add_car_page():
    if request.method == 'POST':
        model = request.form.get('model', '').strip()
        rating = request.form.get('rating', '3')
        file = request.files.get('image')

        if not model:
            flash('Впиши название модели')
            return redirect(url_for('add_car_page'))
        try:
            rating = int(rating)
            if rating < 1 or rating > 5:
                raise ValueError
        except ValueError:
            flash('Оценка должна быть от 1 до 5')
            return redirect(url_for('add_car_page'))
        if not file or file.filename == '':
            flash('Выбери картинку')
            return redirect(url_for('add_car_page'))
        if not allowed_file(file.filename):
            flash('Разрешены только png, jpg, jpeg, webp, gif')
            return redirect(url_for('add_car_page'))

        ext = file.filename.rsplit('.', 1)[1].lower()
        unique_name = f"{uuid.uuid4().hex}.{ext}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
        file.save(filepath)

        add_car(model, unique_name, rating)
        flash(f'Машина «{model}» добавлена в гараж!')
        return redirect(url_for('garage'))

    return render_template('add_car.html', user=session.get('username'), is_admin=True)


init_db()

if __name__ == '__main__':
    app.run(debug=True)

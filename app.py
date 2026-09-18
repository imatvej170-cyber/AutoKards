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
    raise RuntimeError('Не найдена переменная DATABASE_URL. Проверь настройки проекта.')

# RelaxDev подсказал: sslmode нужно убрать
DATABASE_URL = DATABASE_URL.replace('?sslmode=require', '').replace('&sslmode=require', '')

app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 МБ на файл


# ---------- ПОДКЛЮЧЕНИЕ К БАЗЕ ----------
def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    return conn


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
    conn.commit()
    c.close()
    conn.close()


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
    c.execute(
        'INSERT INTO users (username, password_hash, created_at) VALUES (%s, %s, %s)',
        (username, generate_password_hash(password), datetime.now().isoformat())
    )
    conn.commit()
    c.close()
    conn.close()


def get_all_cars():
    """Возвращает список (id, model, rating). Картинки грузим отдельно по id."""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, model, rating FROM cars ORDER BY id DESC')
    rows = c.fetchall()
    c.close()
    conn.close()
    return rows


def add_car(model, rating, image_data, image_mime):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        'INSERT INTO cars (model, rating, image_data, image_mime, created_at) '
        'VALUES (%s, %s, %s, %s, %s)',
        (model, rating, psycopg2.Binary(image_data), image_mime, datetime.now().isoformat())
    )
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

def delete_car(car_id):
    """Удаляет машину из базы по id."""
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM cars WHERE id = %s', (car_id,))
    conn.commit()
    c.close()
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


ALLOWED_MIME = {'image/png', 'image/jpeg', 'image/webp', 'image/gif'}


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
        if file.mimetype not in ALLOWED_MIME:
            flash('Разрешены только PNG, JPG, WEBP, GIF')
            return redirect(url_for('add_car_page'))

        image_data = file.read()
        add_car(model, rating, image_data, file.mimetype)
        flash(f'Машина «{model}» добавлена в гараж!')
        return redirect(url_for('garage'))

    return render_template('add_car.html', user=session.get('username'), is_admin=True)


@app.route('/car_image/<int:car_id>')
def car_image(car_id):
    """Отдаёт картинку машины из базы."""
    row = get_car_image(car_id)
    if not row:
        return '', 404
    image_data, mime = row
    return Response(bytes(image_data), mimetype=mime)

@app.route('/garage/delete/<int:car_id>', methods=['POST'])
@admin_required
def delete_car_page(car_id):
    """Удаление машины — только для админа."""
    delete_car(car_id)
    flash('Машина удалена из гаража')
    return redirect(url_for('garage'))


init_db()

if __name__ == '__main__':
    app.run(debug=True)

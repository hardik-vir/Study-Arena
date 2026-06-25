import os
from datetime import date, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# --- SECURE CONFIGURATION ---
# 1. The Secret Key: Grabs from Render Environment, or uses a fallback locally
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'super_secret_arena_key_123')

# 2. Database Routing: Grabs Render Postgres URL, or defaults to local absolute path SQLite
basedir = os.path.abspath(os.path.dirname(__file__))
default_sqlite_url = 'sqlite:///' + os.path.join(basedir, 'arena.db')
database_url = os.environ.get('DATABASE_URL', default_sqlite_url)

# Fix for older Postgres URL formatting
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize tools
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- DATABASE MODELS ---
class User(UserMixin, db.Model):
    __tablename__ = 'arena_users' # NEW: Forces Postgres to create a brand new, updated table!
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    total_focus_time = db.Column(db.Integer, default=0)
    
    # NEW (Step 3): Columns to track daily streaks!
    current_streak = db.Column(db.Integer, default=0)
    last_focus_date = db.Column(db.Date, nullable=True)

    # Automatically calculates rank based on time
    @property
    def rank(self):
        if self.total_focus_time < 60:
            return "Novice 🥉"
        elif self.total_focus_time < 600:
            return "Scholar 🥈"
        elif self.total_focus_time < 3000:
            return "Deep Work Master 🥇"
        else:
            return "Grandmaster 👑"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- THE ROUTES ---
@app.route('/')
@login_required
def home():
    # Fetch top 10 users for the leaderboard
    top_users = User.query.order_by(User.total_focus_time.desc()).limit(10).all()
    return render_template('index.html', user=current_user, top_users=top_users)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('home'))
        flash('Invalid username or password')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user:
            flash('Username already exists')
            return redirect(url_for('register'))
        new_user = User(username=username, password=generate_password_hash(password, method='pbkdf2:sha256'))
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        return redirect(url_for('home'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/update_time', methods=['POST'])
@login_required
def update_time():
    """ This gets called silently by JavaScript when a timer finishes """
    data = request.get_json()
    minutes = data.get('minutes', 0)
    
    # 1. Update their total time
    current_user.total_focus_time += minutes
    
    # 2. NEW (Step 3): Calculate their Daily Streak
    today = date.today()
    if current_user.last_focus_date == today - timedelta(days=1):
        # They studied yesterday! Increase streak.
        current_user.current_streak += 1
    elif current_user.last_focus_date != today:
        # They missed a day (or it's their first time). Reset streak to 1.
        current_user.current_streak = 1
        
    # Mark that they studied today
    current_user.last_focus_date = today
    
    db.session.commit()
    
    return jsonify({'status': 'success'})

# --- DATABASE CREATION (Safe for Gunicorn/Render) ---
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
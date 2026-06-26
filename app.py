import os
from datetime import date, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func # NEW: Required for calculating pie chart data

app = Flask(__name__)

# --- SECURE CONFIGURATION ---
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'super_secret_arena_key_123')

basedir = os.path.abspath(os.path.dirname(__file__))
default_sqlite_url = 'sqlite:///' + os.path.join(basedir, 'arena.db')
database_url = os.environ.get('DATABASE_URL', default_sqlite_url)

if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- DATABASE MODELS ---
class User(UserMixin, db.Model):
    __tablename__ = 'arena_users' 
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    total_focus_time = db.Column(db.Integer, default=0)
    current_streak = db.Column(db.Integer, default=0)
    last_focus_date = db.Column(db.Date, nullable=True)

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

# NEW: Table to track individual sessions for the Spotify Wrapped Insights
class FocusSession(db.Model):
    __tablename__ = 'focus_sessions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('arena_users.id'), nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False)
    category = db.Column(db.String(50), nullable=False, default="General")
    date = db.Column(db.DateTime, default=db.func.current_timestamp())

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- THE ROUTES ---
@app.route('/')
@login_required
def home():
    top_users = User.query.order_by(User.total_focus_time.desc()).limit(10).all()
    
    # NEW: Calculate pie chart data for the current user
    category_data = db.session.query(
        FocusSession.category, 
        func.sum(FocusSession.duration_minutes)
    ).filter(FocusSession.user_id == current_user.id).group_by(FocusSession.category).all()
    
    # Format data for Chart.js (e.g., {'Coding': 120, 'Reading': 60})
    insights = {cat: int(mins) for cat, mins in category_data}
    
    # If they haven't studied yet, give the chart empty placeholder data
    if not insights:
        insights = {"Start a timer to see insights": 1}

    return render_template('index.html', user=current_user, top_users=top_users, insights=insights)

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
    data = request.get_json()
    minutes = data.get('minutes', 0)
    category = data.get('category', 'General') # NEW: Grab the category
    
    # 1. Update total time & Streak
    current_user.total_focus_time += minutes
    today = date.today()
    if current_user.last_focus_date == today - timedelta(days=1):
        current_user.current_streak += 1
    elif current_user.last_focus_date != today:
        current_user.current_streak = 1
    current_user.last_focus_date = today
    
    # 2. NEW: Save the specific session for the Pie Chart
    new_session = FocusSession(user_id=current_user.id, duration_minutes=minutes, category=category)
    db.session.add(new_session)
    
    db.session.commit()
    return jsonify({'status': 'success'})

# --- DATABASE CREATION ---
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
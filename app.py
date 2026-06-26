import os
from datetime import date, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

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
    __tablename__ = 'users_v5' # Clean Slate V5
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    total_focus_time = db.Column(db.Integer, default=0)
    current_streak = db.Column(db.Integer, default=0)
    last_focus_date = db.Column(db.Date, nullable=True)

    @property
    def rank(self):
        time = self.total_focus_time or 0
        if time < 60: return "Novice 🥉"
        elif time < 600: return "Scholar 🥈"
        elif time < 3000: return "Deep Work Master 🥇"
        else: return "Grandmaster 👑"

class FocusSession(db.Model):
    __tablename__ = 'sessions_v5' # Clean Slate V5
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users_v5.id'), nullable=False)
    duration_minutes = db.Column(db.Integer, default=0)
    category = db.Column(db.String(50), default="General")

@login_manager.user_loader
def load_user(user_id):
    # THE FIX: Universally safe user loading for both old and new Flask versions
    if hasattr(db.session, 'get'):
        return db.session.get(User, int(user_id))
    return User.query.get(int(user_id))

# --- THE ROUTES ---
@app.route('/')
@login_required
def home():
    # 1. Safely load leaderboard
    try:
        top_users = User.query.order_by(User.total_focus_time.desc()).limit(10).all()
    except:
        db.session.rollback()
        top_users = []
    
    # 2. THE BLUNDER FIX: Calculating the pie chart in pure Python, NOT SQL!
    insights = {}
    try:
        user_sessions = FocusSession.query.filter_by(user_id=current_user.id).all()
        for s in user_sessions:
            cat = s.category or "General"
            mins = s.duration_minutes or 0
            insights[cat] = insights.get(cat, 0) + mins
    except Exception as e:
        print("Insights Math Error:", e)
        db.session.rollback()
        
    if not insights:
        insights = {"Start a timer to see insights": 1}

    return render_template('index.html', user=current_user, top_users=top_users, insights=insights)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        try:
            user = User.query.filter_by(username=username).first()
            if user and check_password_hash(user.password, password):
                login_user(user)
                return redirect(url_for('home'))
            flash('Invalid username or password')
        except Exception as e:
            print("Login Error:", e)
            db.session.rollback()
            flash('Database error... Please try again.')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        try:
            user = User.query.filter_by(username=username).first()
            if user:
                flash('Username already exists')
                return redirect(url_for('register'))
            
            new_user = User(
                username=username, 
                password=generate_password_hash(password, method='pbkdf2:sha256'),
                total_focus_time=0,
                current_streak=0
            )
            db.session.add(new_user)
            db.session.commit()
            login_user(new_user)
            return redirect(url_for('home'))
        except Exception as e:
            print("Register Error:", e)
            db.session.rollback()
            flash('Database error... Please try again.')
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
    category = data.get('category', 'General') 
    
    try:
        current_user.total_focus_time = (current_user.total_focus_time or 0) + minutes
        
        today = date.today()
        if current_user.last_focus_date == today - timedelta(days=1):
            current_user.current_streak = (current_user.current_streak or 0) + 1
        elif current_user.last_focus_date != today:
            current_user.current_streak = 1
        current_user.last_focus_date = today
        
        new_session = FocusSession(user_id=current_user.id, duration_minutes=minutes, category=category)
        db.session.add(new_session)
        
        db.session.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        print("Update Time Error:", e)
        db.session.rollback()
        return jsonify({'status': 'error'})

# --- DATABASE CREATION ---
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
import os
import traceback
from datetime import date, timedelta, datetime
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
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {"pool_pre_ping": True, "pool_recycle": 300}

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@app.errorhandler(Exception)
def handle_exception(e):
    db.session.rollback()
    trace = traceback.format_exc()
    print("CRITICAL CRASH:", trace)
    return f"""
    <div style="background:#0f172a; color:#ef4444; padding:30px; font-family:monospace; height:100vh;">
        <h2>⚠️ CRITICAL SYSTEM CRASH DETECTED</h2>
        <textarea style="width:100%; height:400px; background:#1e293b; color:#38bdf8; border:2px solid #ef4444; padding:15px;">{trace}</textarea>
    </div>
    """, 500

# --- DATABASE MODELS ---
class User(UserMixin, db.Model):
    __tablename__ = 'users_v7' # THE FIX: Bumped to V7 for Heatmap support
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False) 
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
    __tablename__ = 'sessions_v7' # THE FIX: Bumped to V7 
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users_v7.id'), nullable=False) # THE FIX: Updated Foreign Key
    duration_minutes = db.Column(db.Integer, default=0)
    category = db.Column(db.String(50), default="General")
    date = db.Column(db.DateTime, default=db.func.current_timestamp()) # The new Heatmap column!

@login_manager.user_loader
def load_user(user_id):
    if hasattr(db.session, 'get'):
        return db.session.get(User, int(user_id))
    return User.query.get(int(user_id))

# --- THE ROUTES ---
@app.route('/')
@login_required
def home():
    top_users = User.query.order_by(User.total_focus_time.desc()).limit(10).all()
    
    # 1. Calculate Insights (Pie Chart)
    insights = {}
    user_sessions = FocusSession.query.filter_by(user_id=current_user.id).all()
    for s in user_sessions:
        cat = s.category or "General"
        mins = s.duration_minutes or 0
        insights[cat] = insights.get(cat, 0) + mins
    if not insights:
        insights = {"Start a timer to see insights": 1}

    # 2. Calculate Heatmap (Last 30 Days)
    heatmap_data = []
    try:
        today = date.today()
        thirty_days_ago = today - timedelta(days=30)
        recent_sessions = FocusSession.query.filter(FocusSession.user_id == current_user.id, FocusSession.date >= thirty_days_ago).all()
        
        # Extract unique dates the user was active
        active_dates = {s.date.date() for s in recent_sessions if s.date}
        
        # Generate true/false for the last 30 days
        for i in range(30):
            d = today - timedelta(days=29 - i)
            heatmap_data.append(d in active_dates)
    except Exception as e:
        print("Heatmap Error:", e)
        db.session.rollback()
        heatmap_data = [False] * 30

    return render_template('index.html', user=current_user, top_users=top_users, insights=insights, heatmap_data=heatmap_data)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if not username or not password:
            flash('Username and password cannot be empty.')
            return redirect(url_for('login'))
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('home'))
        flash('Invalid username or password')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if not username or not password:
            flash('Username and password cannot be empty.')
            return redirect(url_for('register'))
        user = User.query.filter_by(username=username).first()
        if user:
            flash('Username already exists')
            return redirect(url_for('register'))
        new_user = User(
            username=username, 
            password=generate_password_hash(password, method='pbkdf2:sha256'),
            total_focus_time=0, current_streak=0
        )
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
    minutes = int(float(data.get('minutes', 0))) 
    category = data.get('category', 'General') 
    
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

@app.route('/reset_stats', methods=['POST'])
@login_required
def reset_stats():
    try:
        current_user.total_focus_time = 0
        current_user.current_streak = 0
        current_user.last_focus_date = None
        FocusSession.query.filter_by(user_id=current_user.id).delete()
        db.session.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/delete_account', methods=['POST'])
@login_required
def delete_account():
    try:
        FocusSession.query.filter_by(user_id=current_user.id).delete()
        db.session.delete(current_user)
        db.session.commit()
        logout_user()
        return jsonify({'status': 'success'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
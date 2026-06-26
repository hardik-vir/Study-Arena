import os
from datetime import date, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func

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

# THE FIX: Prevents Render from randomly dropping idle database connections
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {"pool_pre_ping": True} 

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- DATABASE MODELS ---
class User(UserMixin, db.Model):
    __tablename__ = 'users_v4' # CLEAN SLATE V4
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    
    # THE FIX: Forcing strict 0 defaults to prevent "NoneType" crashes
    total_focus_time = db.Column(db.Integer, default=0, server_default="0", nullable=False)
    current_streak = db.Column(db.Integer, default=0, server_default="0", nullable=False)
    last_focus_date = db.Column(db.Date, nullable=True)

    @property
    def rank(self):
        # THE FIX: Safely handling any potential empty values on fresh accounts
        time = self.total_focus_time or 0
        if time < 60:
            return "Novice 🥉"
        elif time < 600:
            return "Scholar 🥈"
        elif time < 3000:
            return "Deep Work Master 🥇"
        else:
            return "Grandmaster 👑"

class FocusSession(db.Model):
    __tablename__ = 'sessions_v4' # CLEAN SLATE V4
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users_v4.id'), nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False, default=0)
    category = db.Column(db.String(50), nullable=False, default="General")
    date = db.Column(db.DateTime, default=func.now())

@login_manager.user_loader
def load_user(user_id):
    # THE FIX: Modern SQLAlchemy query format to prevent deprecation crashes
    return db.session.get(User, int(user_id)) 

# --- THE ROUTES ---
@app.route('/')
@login_required
def home():
    # Massive safety nets wrapped around database queries
    try:
        top_users = User.query.order_by(User.total_focus_time.desc()).limit(10).all()
    except Exception as e:
        print("Error fetching leaderboard:", e)
        db.session.rollback()
        top_users = []
    
    try:
        category_data = db.session.query(
            FocusSession.category, 
            func.sum(FocusSession.duration_minutes)
        ).filter(FocusSession.user_id == current_user.id).group_by(FocusSession.category).all()
        
        insights = {cat: int(mins) for cat, mins in category_data if mins is not None}
    except Exception as e:
        print("Database Error:", e)
        db.session.rollback()
        insights = {}
        
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
            
            # THE FIX: Explicitly telling the DB that new users start with exactly 0
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
        return jsonify({'status': 'error', 'message': 'Database error'}), 500

# --- DATABASE CREATION ---
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
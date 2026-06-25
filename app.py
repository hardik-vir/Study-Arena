from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os

app = Flask(__name__)
# The secret key keeps user sessions secure
app.config['SECRET_KEY'] = 'super_secret_arena_key_123' 

# NEW: Find the exact folder path where this code lives on the Render server
basedir = os.path.abspath(os.path.dirname(__file__))

# NEW: Combine the exact folder path with the arena.db file name
default_sqlite_url = 'sqlite:///' + os.path.join(basedir, 'arena.db')

# Grab the database URL from Render's environment, or default to the absolute SQLite path
database_url = os.environ.get('DATABASE_URL', default_sqlite_url)

if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
    
app.config['SQLALCHEMY_DATABASE_URI'] = database_url

# Initialize our tools
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login' # Where to send users if they try to access the timer without logging in

# --- THE DATABASE STRUCTURE ---
# This creates a "Table" in our database for Users
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False) # We will save a scrambled hash here
    total_focus_time = db.Column(db.Integer, default=0) # Tracked in minutes
    streak = db.Column(db.Integer, default=0)

# Helps Flask remember who is currently logged in
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- THE ROUTES ---

@app.route('/')
@login_required # This magic word forces users to log in before seeing the timer!
def home():
    # NEW: Fetch the top 10 users sorted by total_focus_time in descending order
    top_users = User.query.order_by(User.total_focus_time.desc()).limit(10).all()
    
    # Pass BOTH the current_user and the top_users list to the HTML
    return render_template('index.html', user=current_user, top_users=top_users)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # 1. Check if the username is already taken
        user = User.query.filter_by(username=username).first()
        if user:
            flash('Username already exists. Please choose another.')
            return redirect(url_for('register'))
        
        # 2. Scramble the password and create the user
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(username=username, password=hashed_password)
        
        # 3. Save to database
        db.session.add(new_user)
        db.session.commit()
        
        # 4. Log them in and send them to the timer
        login_user(new_user)
        return redirect(url_for('home'))
        
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Search the database for this username
        user = User.query.filter_by(username=username).first()
        
        # If user exists AND the password hash matches
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('home'))
        else:
            flash('Login failed. Check your username and password.')
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# NEW: The route that receives the completed timer data
@app.route('/update_stats', methods=['POST'])
@login_required
def update_stats():
    # Receive the JSON data sent from JavaScript
    data = request.get_json()
    minutes_completed = data.get('minutes', 0)
    
    # Update the user's total focus time in the database
    if minutes_completed > 0:
        current_user.total_focus_time += minutes_completed
        # Basic streak logic: If they study, streak is at least 1!
        if current_user.streak == 0:
            current_user.streak = 1 
            
        db.session.commit()
        return {"status": "success", "new_total": current_user.total_focus_time}
    
    return {"status": "error"}, 400

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
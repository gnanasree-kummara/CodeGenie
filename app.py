from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
import requests
import re
import os
import database
from datetime import datetime
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "users.db")

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "fallback_secret")

HF_TOKEN = os.getenv("HF_TOKEN")
HF_API_URL = "https://router.huggingface.co/v1/chat/completions"
HEADERS = {
    "Authorization": f"Bearer {HF_TOKEN}",
    "Content-Type": "application/json"
}

# ─────────────────────────────────────
# DB HELPER
# ─────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def log_activity(user_id, user_name, action, details=""):
    conn = get_db()
    conn.execute(
        "INSERT INTO activity_logs(user_id, user_name, action, details) VALUES(?,?,?,?)",
        (user_id, user_name, action, details)
    )
    conn.commit()
    conn.close()

# ─────────────────────────────────────
# GENERATE CODE
# ─────────────────────────────────────
def generate_code(user_prompt, language="Python"):
    payload = {
        "model": "meta-llama/Llama-3.1-8B-Instruct:cerebras",
        "messages": [
            {"role": "system", "content": f"You are a {language} code generator. Output ONLY raw {language} code. No explanations, no markdown, no backticks. Just the pure {language} code itself."},
            {"role": "user", "content": f"Write a {language} program for: {user_prompt}"}
        ],
        "max_tokens": 800,
        "temperature": 0.2
    }
    try:
        response = requests.post(HF_API_URL, headers=HEADERS, json=payload, timeout=60)
        result = response.json()
        if "choices" in result:
            code = result["choices"][0]["message"]["content"].strip()
            code = re.sub(r'```[\w+#]*\n?', '', code)
            code = code.replace('```', '').strip()
            lines = code.split("\n")
            clean_lines = []
            for line in lines:
                if line and not line.startswith(" ") and not line.startswith("#") and not line.startswith("//") and not any(c in line for c in ["=", ":", "def ", "if ", "for ", "return", "print", "import", "{", "}", ";"]) and len(line.split()) > 4:
                    break
                clean_lines.append(line)
            return "\n".join(clean_lines).strip()
        else:
            return f"# Error: {result}"
    except Exception as e:
        return f"# Connection error: {str(e)}"

# ─────────────────────────────────────
# EXPLAIN CODE
# ─────────────────────────────────────
def explain_code(code, language="Python"):
    payload = {
        "model": "meta-llama/Llama-3.1-8B-Instruct:cerebras",
        "messages": [
            {"role": "system", "content": "You are a code explainer. Explain code in simple numbered steps in plain English. Do not use bullet points (*). Do not include any code blocks. Just simple numbered explanations like: 1. Step one explanation. 2. Step two explanation."},
            {"role": "user", "content": f"Explain this {language} code step by step in simple English:\n{code}"}
        ],
        "max_tokens": 600,
        "temperature": 0.4
    }
    try:
        response = requests.post(HF_API_URL, headers=HEADERS, json=payload, timeout=60)
        result = response.json()
        if "choices" in result:
            return result["choices"][0]["message"]["content"].strip()
        else:
            return f"Error: {result}"
    except Exception as e:
        return f"Connection error: {str(e)}"

# ─────────────────────────────────────
# LOGIN
# ─────────────────────────────────────
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = sqlite3.connect('users.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        user = cursor.execute(
            "SELECT * FROM users WHERE email=?",
            (email,)
        ).fetchone()

        conn.close()

        # User not found
        if not user:
            return render_template("login.html", error="User not found. Please sign up.")

        # Password wrong
        if user['password'] != password:
            return render_template("login.html", error="Incorrect password")

        # Success
        session['user'] = user['name']
        session['user_id'] = user['id']
        return redirect(url_for('home'))

    return render_template("login.html")

# ─────────────────────────────────────
# SIGNUP
# ─────────────────────────────────────
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == "POST":
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO users(name, email, password) VALUES(?,?,?)",
                (name, email, password)
            )
            conn.commit()
        except:
            return render_template("signup.html", error="Email already exists!")
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        conn.close()
        session['user'] = name
        session['user_id'] = user['id']
        log_activity(user['id'], name, "Signup", "New user registered")
        return redirect(url_for('home'))
    return render_template("signup.html")

# ─────────────────────────────────────
# HOME
# ─────────────────────────────────────
@app.route('/home')
def home():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template("home.html", user=session['user'])

# ─────────────────────────────────────
# GENERATE PAGE
# ─────────────────────────────────────
@app.route('/generate-page', methods=['GET', 'POST'])
def generate_page():
    if 'user' not in session:
        return redirect(url_for('login'))

    generated_code = ""
    explanation = ""
    prompt = ""
    language = "Python"

    if request.method == "POST":
        action = request.form.get("action")
        prompt = request.form.get("prompt", "")
        code = request.form.get("code", "")
        language = request.form.get("language", "Python")

        if action == "generate":
            generated_code = generate_code(prompt, language)
            # Save to history
            conn = get_db()
            conn.execute(
                "INSERT INTO code_history(user_id, user_name, language, prompt, generated_code) VALUES(?,?,?,?,?)",
                (session['user_id'], session['user'], language, prompt, generated_code)
            )
            conn.commit()
            conn.close()
            log_activity(session['user_id'], session['user'], "Generate Code", f"Language: {language}, Prompt: {prompt[:50]}")

        elif action == "explain":
            generated_code = code
            explanation = explain_code(code, language)
            log_activity(session['user_id'], session['user'], "Explain Code", f"Language: {language}")

    return render_template(
        "generate.html",
        generated_code=generated_code,
        explanation=explanation,
        prompt=prompt,
        language=language
    )

# ─────────────────────────────────────
# FEEDBACK
# ─────────────────────────────────────
@app.route('/feedback', methods=['GET', 'POST'])
def feedback():
    if 'user' not in session:
        return redirect(url_for('login'))

    success = False
    if request.method == "POST":
        message = request.form.get("message", "")
        rating = request.form.get("rating", 5)
        conn = get_db()
        conn.execute(
            "INSERT INTO feedback(user_id, user_name, message, rating) VALUES(?,?,?,?)",
            (session['user_id'], session['user'], message, rating)
        )
        conn.commit()
        conn.close()
        log_activity(session['user_id'], session['user'], "Feedback", f"Rating: {rating}")
        success = True

    return render_template("feedback.html", user=session['user'], success=success)

# ─────────────────────────────────────
# USER PROFILE
# ─────────────────────────────────────
@app.route('/profile')
def profile():
    if 'user' not in session:
        return redirect(url_for('login'))

    conn = get_db()
    user_info = conn.execute(
        "SELECT * FROM users WHERE id=?", (session['user_id'],)
    ).fetchone()
    history = conn.execute(
        "SELECT * FROM code_history WHERE user_id=? ORDER BY timestamp DESC LIMIT 10",
        (session['user_id'],)
    ).fetchall()
    feedbacks = conn.execute(
        "SELECT * FROM feedback WHERE user_id=? ORDER BY timestamp DESC",
        (session['user_id'],)
    ).fetchall()
    conn.close()

    return render_template("profile.html",
        user=session['user'],
        user_info=user_info,
        history=history,
        feedbacks=feedbacks
    )

# ─────────────────────────────────────
# ADMIN LOGIN
# ─────────────────────────────────────
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    error = None
    if request.method == "POST":
        username = request.form['username']
        password = request.form['password']
        conn = get_db()
        admin = conn.execute(
            "SELECT * FROM admins WHERE username=? AND password=?",
            (username, password)
        ).fetchone()
        conn.close()
        if admin:
            session['admin'] = username
            return redirect(url_for('admin_dashboard'))
        else:
            error = "Invalid admin credentials."
    return render_template("admin_login.html", error=error)

# ─────────────────────────────────────
# ADMIN DASHBOARD
# ─────────────────────────────────────
@app.route('/admin/dashboard')
def admin_dashboard():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))

    conn = get_db()

    # Stats
    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_generations = conn.execute("SELECT COUNT(*) FROM code_history").fetchone()[0]
    total_feedback = conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
    total_logs = conn.execute("SELECT COUNT(*) FROM activity_logs").fetchone()[0]

    # All users
    users = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()

    # Recent code history
    history = conn.execute(
        "SELECT * FROM code_history ORDER BY timestamp DESC LIMIT 20"
    ).fetchall()

    # All feedback
    feedbacks = conn.execute(
        "SELECT * FROM feedback ORDER BY timestamp DESC"
    ).fetchall()

    # Activity logs
    logs = conn.execute(
        "SELECT * FROM activity_logs ORDER BY timestamp DESC LIMIT 50"
    ).fetchall()

    # Language usage for chart
    lang_data = conn.execute(
        "SELECT language, COUNT(*) as count FROM code_history GROUP BY language"
    ).fetchall()

    # Daily activity for chart (last 7 days)
    daily_data = conn.execute("""
        SELECT DATE(timestamp) as day, COUNT(*) as count
        FROM code_history
        GROUP BY DATE(timestamp)
        ORDER BY day DESC LIMIT 7
    """).fetchall()

    # Rating distribution for chart
    rating_data = conn.execute("""
        SELECT rating, COUNT(*) as count
        FROM feedback
        GROUP BY rating
        ORDER BY rating DESC
    """).fetchall()

    conn.close()

    return render_template("admin_dashboard.html",
        total_users=total_users,
        total_generations=total_generations,
        total_feedback=total_feedback,
        total_logs=total_logs,
        users=users,
        history=history,
        feedbacks=feedbacks,
        logs=logs,
        lang_data=lang_data,
        daily_data=daily_data,
        rating_data=rating_data
    )

# ─────────────────────────────────────
# ADMIN LOGOUT
# ─────────────────────────────────────
@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect(url_for('admin_login'))

# ─────────────────────────────────────
# LOGOUT
# ─────────────────────────────────────
@app.route('/logout')
def logout():
    if 'user_id' in session:
        log_activity(session['user_id'], session['user'], "Logout", "User logged out")
    session.pop('user', None)
    session.pop('user_id', None)
    return redirect(url_for('login'))


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS code_history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        user_name TEXT,
        language TEXT,
        prompt TEXT,
        generated_code TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS feedback(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        user_name TEXT,
        message TEXT,
        rating INTEGER,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS activity_logs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        user_name TEXT,
        action TEXT,
        details TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS admins(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL)""")
    cursor.execute("INSERT OR IGNORE INTO admins(username, password) VALUES('admin', 'admin123')")
    conn.commit()
    conn.close()

init_db()
# ─────────────────────────────────────
# RUN
# ─────────────────────────────────────
if __name__ == '__main__':
    app.run(debug=True)
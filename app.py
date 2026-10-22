from flask import Flask, request, session, redirect, jsonify, send_from_directory
import sqlite3
import bcrypt
import os
from datetime import datetime, timedelta

app = Flask(__name__, static_folder="static", static_url_path="")
app.secret_key = "dev-only-fallback-change-me"

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

DB = "site.db"

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            plain_password TEXT,
            role TEXT DEFAULT 'user',
            is_active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS licenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            expires_at TIMESTAMP NOT NULL
        );
    """)
    conn.commit()
    conn.close()
init_db()

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

# --- ავტორიზაცია ---
@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json()
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username=?", (data.get("username"),)).fetchone()
    
    if not user or not bcrypt.checkpw(data.get("password", "").encode(), user["password_hash"].encode()):
        conn.close()
        return jsonify({"ok": False, "error": "არასწორი მონაცემები"}), 401
    
    lic = conn.execute("SELECT * FROM licenses WHERE user_id=?", (user["id"],)).fetchone()
    if lic and datetime.fromisoformat(lic["expires_at"]) < datetime.now():
        conn.close()
        return jsonify({"ok": False, "error": "ვადა ამოიწურა!"}), 402

    session.permanent = False 
    session["user_id"] = user["id"]
    session["role"] = user["role"]
    conn.close()
    return jsonify({"ok": True, "role": user["role"]})

@app.route("/api/logout")
def api_logout():
    session.clear()
    return jsonify({"ok": True})

# --- ადმინის API ---
@app.route("/api/admin/users")
def api_admin_users():
    if session.get("role") != "admin": return jsonify({"ok": False}), 403
    conn = get_db()
    users = conn.execute("""
        SELECT u.id, u.username, u.plain_password, l.expires_at 
        FROM users u LEFT JOIN licenses l ON l.user_id = u.id 
        ORDER BY u.id DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(u) for u in users])

@app.route("/api/admin/create", methods=["POST"])
def api_admin_create():
    if session.get("role") != "admin": return jsonify({"ok": False, "error": "უფლება არ გაქვს"}), 403
    data = request.get_json()
    pw_plain = data.get("password", "")
    pw_hash = bcrypt.hashpw(pw_plain.encode(), bcrypt.gensalt()).decode()
    
    exp_date_str = data.get("expires_at", "")
    try:
        exp = datetime.fromisoformat(exp_date_str).isoformat()
    except:
        exp = datetime.now().isoformat()
    
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("INSERT INTO users (username, password_hash, plain_password) VALUES (?, ?, ?)", (data.get("username"), pw_hash, pw_plain))
        uid = c.lastrowid
        c.execute("INSERT INTO licenses (user_id, expires_at) VALUES (?, ?)", (uid, exp))
        conn.commit()
        return jsonify({"ok": True})
    except Exception:
        return jsonify({"ok": False, "error": "ეს სახელი უკვე დაკავებულია"}), 400
    finally:
        conn.close()

@app.route("/api/admin/delete/<int:uid>", methods=["POST"])
def api_admin_delete(uid):
    if session.get("role") != "admin": return jsonify({"ok": False, "error": "უფლება არ გაქვს"}), 403
    conn = get_db()
    try:
        conn.execute("DELETE FROM licenses WHERE user_id=?", (uid,))
        conn.execute("DELETE FROM users WHERE id=?", (uid,))
        conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    finally:
        conn.close()

@app.route("/api/admin/extend/<int:uid>", methods=["POST"])
def api_admin_extend(uid):
    if session.get("role") != "admin": return jsonify({"ok": False, "error": "უფლება არ გაქვს"}), 403
    data = request.get_json()
    days = int(data.get("days", 0))
    hours = int(data.get("hours", 0))
    minutes = int(data.get("minutes", 0))
    
    conn = get_db()
    try:
        lic = conn.execute("SELECT * FROM licenses WHERE user_id=?", (uid,)).fetchone()
        if lic:
            base = max(datetime.fromisoformat(lic["expires_at"]), datetime.now())
            new_exp = base + timedelta(days=days, hours=hours, minutes=minutes)
            conn.execute("UPDATE licenses SET expires_at=? WHERE user_id=?", (new_exp.isoformat(), uid))
            conn.commit()
            return jsonify({"ok": True})
        else:
            return jsonify({"ok": False, "error": "ლიცენზია ვერ მოიძებნა"}), 404
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    finally:
        conn.close()

@app.route("/api/admin/change_password", methods=["POST"])
def api_admin_change_password():
    if session.get("role") != "admin": return jsonify({"ok": False, "error": "უფლება არ გაქვს"}), 403
    data = request.get_json()
    new_pass = data.get("new_password", "")
    if len(new_pass) < 4: return jsonify({"ok": False, "error": "პაროლი მინიმუმ 4 სიმბოლო"}), 400
    
    pw_hash = bcrypt.hashpw(new_pass.encode(), bcrypt.gensalt()).decode()
    conn = get_db()
    conn.execute("UPDATE users SET password_hash=?, plain_password=? WHERE id=?", (pw_hash, new_pass, session["user_id"]))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# --- ძებნა ---
@app.route("/api/search", methods=["GET"])
def api_search():
    if "user_id" not in session: return jsonify({"error": "ავტორიზაცია საჭიროა"}), 401
    
    query = request.args.get("q", "").lower()
    field = request.args.get("field", "all")
    
    results = []
    filename = "2012.txt"
    
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                
                if '\t' in line: parts = line.split('\t')
                elif ',' in line: parts = line.split(',')
                else: parts = line.split()
                
                match = False
                if field == "all":
                    match = any(query in cell.lower() for cell in parts)
                else:
                    idx = int(field)
                    if idx < len(parts) and query in parts[idx].lower():
                        match = True
                
                if match:
                    results.append(parts)
                    if len(results) >= 500: break
                
    return jsonify(results)

# --- გვერდები ---
@app.route("/admin")
def admin_page():
    if session.get("role") != "admin": return redirect("/login.html")
    return send_from_directory("static", "admin.html")

@app.route("/database")
def database_page():
    if "user_id" not in session: return redirect("/login.html")
    return send_from_directory("static", "database.html")

# --- SMS Bomber ჩამოტვირთვა ---
@app.route("/download_sms")
def download_sms():
    if "user_id" not in session: return redirect("/login.html")
    return send_from_directory("static", "smsbomber.exe", as_attachment=True)

@app.route("/")
def index():
    return redirect("/database")

with app.app_context():
    conn = get_db()
    if not conn.execute("SELECT * FROM users WHERE role='admin'").fetchone():
        pw = bcrypt.hashpw("admin123".encode(), bcrypt.gensalt()).decode()
        c = conn.cursor()
        c.execute("INSERT INTO users (username, password_hash, plain_password, role) VALUES ('admin', ?, 'admin123', 'admin')", (pw,))
        c.execute("INSERT INTO licenses (user_id, expires_at) VALUES (?, ?)", (c.lastrowid, (datetime.now() + timedelta(days=36500)).isoformat()))
        conn.commit()
    conn.close()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
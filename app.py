import os
import sqlite3
import secrets
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, abort, jsonify, flash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")
DB = os.path.join(os.path.dirname(__file__), "database.db")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pairs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            left_text TEXT NOT NULL,
            right_text TEXT NOT NULL,
            FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            score INTEGER NOT NULL,
            total INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    conn.close()

def logged_in():
    return session.get("admin") is True

def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not logged_in():
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapped

@app.route("/")
def home():
    if logged_in():
        return redirect(url_for("admin"))
    return render_template("home.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if secrets.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
            session["admin"] = True
            return redirect(request.args.get("next") or url_for("admin"))
        flash("Құпиясөз қате.", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/admin")
@login_required
def admin():
    conn = db()
    tasks = conn.execute("""
        SELECT t.*, COUNT(p.id) AS pair_count
        FROM tasks t LEFT JOIN pairs p ON p.task_id=t.id
        GROUP BY t.id ORDER BY t.id DESC
    """).fetchall()
    conn.close()
    return render_template("admin.html", tasks=tasks)

@app.route("/admin/new", methods=["GET", "POST"])
@login_required
def new_task():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        lefts = request.form.getlist("left[]")
        rights = request.form.getlist("right[]")
        pairs = [(a.strip(), b.strip()) for a,b in zip(lefts, rights) if a.strip() and b.strip()]
        if not title or not pairs:
            flash("Атауы мен кемінде бір жұп енгізіңіз.", "error")
            return render_template("editor.html", task=None, pairs=pairs)
        slug = secrets.token_urlsafe(7)
        conn = db()
        while conn.execute("SELECT 1 FROM tasks WHERE slug=?", (slug,)).fetchone():
            slug = secrets.token_urlsafe(7)
        cur = conn.execute("INSERT INTO tasks(title,slug) VALUES(?,?)", (title, slug))
        task_id = cur.lastrowid
        conn.executemany("INSERT INTO pairs(task_id,left_text,right_text) VALUES(?,?,?)",
                         [(task_id,a,b) for a,b in pairs])
        conn.commit()
        conn.close()
        flash("Тапсырма сақталды.", "success")
        return redirect(url_for("admin"))
    return render_template("editor.html", task=None, pairs=[("", "")])

@app.route("/admin/edit/<int:task_id>", methods=["GET", "POST"])
@login_required
def edit_task(task_id):
    conn = db()
    task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not task:
        conn.close()
        abort(404)
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        lefts = request.form.getlist("left[]")
        rights = request.form.getlist("right[]")
        pairs = [(a.strip(), b.strip()) for a,b in zip(lefts, rights) if a.strip() and b.strip()]
        if not title or not pairs:
            conn.close()
            flash("Атауы мен кемінде бір жұп енгізіңіз.", "error")
            return render_template("editor.html", task=task, pairs=pairs)
        conn.execute("UPDATE tasks SET title=? WHERE id=?", (title, task_id))
        conn.execute("DELETE FROM pairs WHERE task_id=?", (task_id,))
        conn.executemany("INSERT INTO pairs(task_id,left_text,right_text) VALUES(?,?,?)",
                         [(task_id,a,b) for a,b in pairs])
        conn.commit()
        conn.close()
        flash("Өзгерістер сақталды.", "success")
        return redirect(url_for("admin"))
    pairs = conn.execute("SELECT left_text,right_text FROM pairs WHERE task_id=? ORDER BY id", (task_id,)).fetchall()
    conn.close()
    return render_template("editor.html", task=task, pairs=pairs)

@app.post("/admin/delete/<int:task_id>")
@login_required
def delete_task(task_id):
    conn = db()
    conn.execute("DELETE FROM results WHERE task_id=?", (task_id,))
    conn.execute("DELETE FROM pairs WHERE task_id=?", (task_id,))
    conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    conn.commit()
    conn.close()
    flash("Тапсырма өшірілді.", "success")
    return redirect(url_for("admin"))

@app.route("/admin/results/<int:task_id>")
@login_required
def results(task_id):
    conn = db()
    task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    rows = conn.execute("SELECT * FROM results WHERE task_id=? ORDER BY id DESC", (task_id,)).fetchall()
    conn.close()
    if not task: abort(404)
    return render_template("results.html", task=task, results=rows)

@app.route("/task/<slug>")
def student(slug):
    conn = db()
    task = conn.execute("SELECT * FROM tasks WHERE slug=?", (slug,)).fetchone()
    if not task:
        conn.close()
        abort(404)
    pairs = conn.execute("SELECT id,left_text,right_text FROM pairs WHERE task_id=? ORDER BY id", (task["id"],)).fetchall()
    conn.close()
    return render_template("student.html", task=task, pairs=pairs)

@app.post("/task/<slug>/submit")
def submit(slug):
    data = request.get_json(force=True)
    conn = db()
    task = conn.execute("SELECT * FROM tasks WHERE slug=?", (slug,)).fetchone()
    if not task:
        conn.close()
        return jsonify({"error":"Тапсырма табылмады"}), 404
    pairs = conn.execute("SELECT id,right_text FROM pairs WHERE task_id=?", (task["id"],)).fetchall()
    answers = data.get("answers", {})
    score = 0
    for p in pairs:
        if answers.get(str(p["id"])) == p["right_text"]:
            score += 1
    conn.execute("INSERT INTO results(task_id,score,total) VALUES(?,?,?)",
                 (task["id"], score, len(pairs)))
    conn.commit()
    conn.close()
    return jsonify({"score":score, "total":len(pairs)})

@app.context_processor
def inject():
    return {"logged_in": logged_in()}

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

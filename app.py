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
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = db()
    conn.execute("""CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        slug TEXT UNIQUE NOT NULL,
        difficulty TEXT NOT NULL DEFAULT 'Қалыпты',
        timer_seconds INTEGER NOT NULL DEFAULT 0,
        shuffle INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS pairs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        left_text TEXT NOT NULL,
        right_text TEXT NOT NULL,
        FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        student_name TEXT NOT NULL DEFAULT 'Аноним',
        score INTEGER NOT NULL,
        total INTEGER NOT NULL,
        time_seconds INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
    )""")
    # Upgrade older databases safely.
    for sql in [
        "ALTER TABLE tasks ADD COLUMN difficulty TEXT NOT NULL DEFAULT 'Қалыпты'",
        "ALTER TABLE tasks ADD COLUMN timer_seconds INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE tasks ADD COLUMN shuffle INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE results ADD COLUMN student_name TEXT NOT NULL DEFAULT 'Аноним'",
        "ALTER TABLE results ADD COLUMN time_seconds INTEGER NOT NULL DEFAULT 0",
    ]:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass
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
    tasks = conn.execute("""SELECT t.*, COUNT(p.id) AS pair_count,
        (SELECT COUNT(*) FROM results r WHERE r.task_id=t.id) AS result_count
        FROM tasks t LEFT JOIN pairs p ON p.task_id=t.id
        GROUP BY t.id ORDER BY t.id DESC""").fetchall()
    conn.close()
    return render_template("admin.html", tasks=tasks)


def clean_settings(form):
    difficulty = form.get("difficulty", "Қалыпты")
    if difficulty not in {"Жеңіл", "Қалыпты", "Қиын", "Хардкор"}:
        difficulty = "Қалыпты"
    try:
        timer = max(0, min(1800, int(form.get("timer_seconds", "0"))))
    except ValueError:
        timer = 0
    if difficulty == "Хардкор" and timer == 0:
        timer = 45
    return difficulty, timer, 1 if form.get("shuffle") == "on" else 0


def collect_pairs(form):
    lefts = form.getlist("left[]")
    rights = form.getlist("right[]")
    return [(a.strip(), b.strip()) for a, b in zip(lefts, rights) if a.strip() and b.strip()]


@app.route("/admin/new", methods=["GET", "POST"])
@login_required
def new_task():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        pairs = collect_pairs(request.form)
        difficulty, timer, shuffle = clean_settings(request.form)
        if not title or not pairs:
            flash("Атауы мен кемінде бір жұп енгізіңіз.", "error")
            return render_template("editor.html", task=None, pairs=pairs, form=request.form)
        slug = secrets.token_urlsafe(7)
        conn = db()
        while conn.execute("SELECT 1 FROM tasks WHERE slug=?", (slug,)).fetchone():
            slug = secrets.token_urlsafe(7)
        cur = conn.execute("INSERT INTO tasks(title,slug,difficulty,timer_seconds,shuffle) VALUES(?,?,?,?,?)",
                           (title, slug, difficulty, timer, shuffle))
        task_id = cur.lastrowid
        conn.executemany("INSERT INTO pairs(task_id,left_text,right_text) VALUES(?,?,?)",
                         [(task_id, a, b) for a, b in pairs])
        conn.commit()
        conn.close()
        flash("Тапсырма сақталды. Оқушыға сілтемені жіберуге болады.", "success")
        return redirect(url_for("admin"))
    return render_template("editor.html", task=None, pairs=[("", "")], form=None)


@app.route("/admin/edit/<int:task_id>", methods=["GET", "POST"])
@login_required
def edit_task(task_id):
    conn = db()
    task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not task:
        conn.close(); abort(404)
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        pairs = collect_pairs(request.form)
        difficulty, timer, shuffle = clean_settings(request.form)
        if not title or not pairs:
            conn.close()
            flash("Атауы мен кемінде бір жұп енгізіңіз.", "error")
            return render_template("editor.html", task=task, pairs=pairs, form=request.form)
        conn.execute("UPDATE tasks SET title=?,difficulty=?,timer_seconds=?,shuffle=? WHERE id=?",
                     (title, difficulty, timer, shuffle, task_id))
        conn.execute("DELETE FROM pairs WHERE task_id=?", (task_id,))
        conn.executemany("INSERT INTO pairs(task_id,left_text,right_text) VALUES(?,?,?)",
                         [(task_id, a, b) for a, b in pairs])
        conn.commit(); conn.close()
        flash("Өзгерістер сақталды.", "success")
        return redirect(url_for("admin"))
    pairs = conn.execute("SELECT left_text,right_text FROM pairs WHERE task_id=? ORDER BY id", (task_id,)).fetchall()
    conn.close()
    return render_template("editor.html", task=task, pairs=pairs, form=None)


@app.post("/admin/delete/<int:task_id>")
@login_required
def delete_task(task_id):
    conn = db()
    conn.execute("DELETE FROM results WHERE task_id=?", (task_id,))
    conn.execute("DELETE FROM pairs WHERE task_id=?", (task_id,))
    conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    conn.commit(); conn.close()
    flash("Тапсырма өшірілді.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/results/<int:task_id>")
@login_required
def results(task_id):
    conn = db()
    task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    rows = conn.execute("SELECT * FROM results WHERE task_id=? ORDER BY score DESC, time_seconds ASC, id DESC", (task_id,)).fetchall()
    conn.close()
    if not task: abort(404)
    return render_template("results.html", task=task, results=rows)


@app.route("/task/<slug>")
def student(slug):
    conn = db()
    task = conn.execute("SELECT * FROM tasks WHERE slug=?", (slug,)).fetchone()
    if not task:
        conn.close(); abort(404)
    pairs = conn.execute("SELECT id,left_text,right_text FROM pairs WHERE task_id=? ORDER BY id", (task["id"],)).fetchall()
    conn.close()
    return render_template("student.html", task=task, pairs=pairs)


@app.post("/task/<slug>/submit")
def submit(slug):
    data = request.get_json(force=True) or {}
    student_name = (data.get("student_name") or "Аноним").strip()[:80] or "Аноним"
    try:
        elapsed = max(0, min(86400, int(data.get("time_seconds", 0))))
    except (TypeError, ValueError):
        elapsed = 0
    conn = db()
    task = conn.execute("SELECT * FROM tasks WHERE slug=?", (slug,)).fetchone()
    if not task:
        conn.close(); return jsonify({"error": "Тапсырма табылмады"}), 404
    pairs = conn.execute("SELECT id FROM pairs WHERE task_id=?", (task["id"],)).fetchall()
    answers = data.get("answers", {}) or {}
    score = sum(1 for p in pairs if answers.get(str(p["id"])) == str(p["id"]))
    conn.execute("INSERT INTO results(task_id,student_name,score,total,time_seconds) VALUES(?,?,?,?,?)",
                 (task["id"], student_name, score, len(pairs), elapsed))
    conn.commit(); conn.close()
    return jsonify({"score": score, "total": len(pairs), "student_name": student_name})


@app.context_processor
def inject():
    return {"logged_in": logged_in()}


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)

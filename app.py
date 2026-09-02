import os, sqlite3, secrets, json, re, hashlib
from functools import wraps
from datetime import timedelta
from flask import Flask, render_template, request, redirect, url_for, session, abort, jsonify, flash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'teacher-sabina-change-this-secret')
app.permanent_session_lifetime = timedelta(days=30)
DB = os.path.join(os.path.dirname(__file__), 'database.db')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')

ACTIVITY_TYPES = {
    'matching': '🔗 Сәйкестендіру', 'quiz': '🧠 Тест / Викторина', 'fill': '✍️ Бос орынды толтыр',
    'truefalse': '⚡ Дұрыс / Бұрыс', 'categorize': '🗂️ Санаттарға бөлу', 'ordering': '🔢 Ретін тап',
    'flashcards': '🃏 Флеш-карталар', 'wordpuzzle': '🔤 Сөзжұмбақ', 'imagequiz': '🖼️ Сурет бойынша',
    'audioquiz': '🎧 Аудио сұрақ'
}
DIFFICULTIES = {'Жеңіл','Қалыпты','Қиын','Хардкор'}


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c


def hash_password(password):
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def init_db():
    c = db()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('teacher','student')),
        xp INTEGER NOT NULL DEFAULT 0, streak INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, slug TEXT UNIQUE NOT NULL,
        difficulty TEXT NOT NULL DEFAULT 'Қалыпты', timer_seconds INTEGER NOT NULL DEFAULT 0,
        shuffle INTEGER NOT NULL DEFAULT 1, activity_type TEXT NOT NULL DEFAULT 'matching',
        data_json TEXT NOT NULL DEFAULT '[]', owner_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE SET NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS pairs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL, left_text TEXT NOT NULL, right_text TEXT NOT NULL,
        FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS results (
        id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL, student_name TEXT NOT NULL DEFAULT 'Аноним',
        score INTEGER NOT NULL, total INTEGER NOT NULL, time_seconds INTEGER NOT NULL DEFAULT 0, user_id INTEGER,
        xp_earned INTEGER NOT NULL DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE, FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS drafts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, task_id INTEGER, payload_json TEXT NOT NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(user_id, task_id), FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS live_games (
        id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL, teacher_id INTEGER, pin TEXT UNIQUE NOT NULL,
        status TEXT NOT NULL DEFAULT 'lobby', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE, FOREIGN KEY(teacher_id) REFERENCES users(id) ON DELETE SET NULL)''')
    # Safe migrations for the V6 database.
    migrations = [
        ('tasks','owner_id','INTEGER'), ('results','user_id','INTEGER'), ('results','xp_earned','INTEGER NOT NULL DEFAULT 0')
    ]
    for table, col, typ in migrations:
        try: c.execute(f'ALTER TABLE {table} ADD COLUMN {col} {typ}')
        except sqlite3.OperationalError: pass
    c.commit(); c.close()


def current_user():
    uid = session.get('user_id')
    if not uid: return None
    c = db(); u = c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone(); c.close()
    return u


def logged_in(): return bool(session.get('user_id') or session.get('admin'))

def teacher_logged_in(): return session.get('role') == 'teacher' or session.get('admin') is True

def student_logged_in(): return session.get('role') == 'student'


def role_required(role):
    def deco(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if role == 'teacher' and not teacher_logged_in(): return redirect(url_for('login', next=request.path))
            if role == 'student' and not student_logged_in(): return redirect(url_for('login', next=request.path, role='student'))
            return f(*args, **kwargs)
        return wrapped
    return deco


def valid_email(email): return bool(re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email or ''))


def level_for(xp): return max(1, xp // 250 + 1)


def level_progress(xp):
    base = (level_for(xp)-1)*250; nxt = level_for(xp)*250
    return xp-base, nxt-base, int(((xp-base)/(nxt-base))*100) if nxt>base else 0


def achievements_for(xp, result_count=0, best_pct=0):
    return [
        ('🏆','Бірінші жеңіс', result_count >= 1), ('🎯','100% нәтиже', best_pct >= 100),
        ('🔥','7 күндік streak', False), ('⚡','Жылдам жауап', False), ('🧠','10 тапсырма', result_count >= 10),
        ('👑','Бірінші орын', False)
    ]


def teacher_user_id(): return current_user()['id'] if current_user() else None


def clean_settings(form):
    d=form.get('difficulty','Қалыпты'); d=d if d in DIFFICULTIES else 'Қалыпты'
    try: timer=max(0,min(1800,int(form.get('timer_seconds','0'))))
    except (ValueError,TypeError): timer=0
    if d=='Хардкор' and timer==0: timer=45
    return d,timer,1 if form.get('shuffle')=='on' else 0


def activity_type(form):
    v=form.get('activity_type','matching'); return v if v in ACTIVITY_TYPES else 'matching'


def collect_items(form, kind):
    if kind in {'quiz','imagequiz','audioquiz'}:
        qs=form.getlist('question[]'); correct=form.getlist('correct[]'); media=form.getlist('media[]')
        cols=[form.getlist(f'option{i}[]') for i in range(1,5)]; items=[]
        for i,q in enumerate(qs):
            opts=[cols[j][i].strip() if i<len(cols[j]) else '' for j in range(4)]
            q=q.strip(); c=correct[i].strip() if i<len(correct) else ''; m=media[i].strip() if i<len(media) else ''
            opts=[x for x in opts if x]
            if q and c and c in opts and (kind=='quiz' or m):
                item={'question':q,'correct':c,'options':opts}
                if kind in {'imagequiz','audioquiz'}: item['media']=m
                items.append(item)
        return items
    if kind=='truefalse':
        return [{'question':q.strip(),'answer':a} for q,a in zip(form.getlist('question[]'),form.getlist('answer[]')) if q.strip() and a in {'true','false'}]
    if kind in {'fill','wordpuzzle'}:
        return [{'question':q.strip(),'answer':a.strip()} for q,a in zip(form.getlist('question[]'),form.getlist('answer[]')) if q.strip() and a.strip()]
    if kind=='categorize':
        qs=form.getlist('question[]'); cs=form.getlist('correct[]'); cats=form.getlist('categories[]'); out=[]
        for i,q in enumerate(qs):
            c=cs[i].strip() if i<len(cs) else ''; raw=cats[i] if i<len(cats) else ''
            if q.strip() and c: out.append({'question':q.strip(),'correct':c,'categories':[x.strip() for x in raw.split('|') if x.strip()]})
        return out
    if kind=='ordering':
        qs=form.getlist('question[]'); os_=form.getlist('order[]'); return [{'question':q.strip(),'order':[x.strip() for x in os_[i].split('|') if x.strip()]} for i,q in enumerate(qs) if q.strip() and i<len(os_) and os_[i].strip()]
    if kind=='flashcards':
        return [{'front':a.strip(),'back':b.strip()} for a,b in zip(form.getlist('front[]'),form.getlist('back[]')) if a.strip() and b.strip()]
    return [{'left':a.strip(),'right':b.strip()} for a,b in zip(form.getlist('left[]'),form.getlist('right[]')) if a.strip() and b.strip()]


def save_task(c,title,slug,difficulty,timer,shuffle,kind,items,owner_id=None):
    cur=c.execute('INSERT INTO tasks(title,slug,difficulty,timer_seconds,shuffle,activity_type,data_json,owner_id) VALUES(?,?,?,?,?,?,?,?)',
                  (title,slug,difficulty,timer,shuffle,kind,json.dumps(items,ensure_ascii=False),owner_id))
    tid=cur.lastrowid
    if kind=='matching': c.executemany('INSERT INTO pairs(task_id,left_text,right_text) VALUES(?,?,?)',[(tid,x['left'],x['right']) for x in items])
    return tid


def editor_context(form=None,task=None,items=None,initial_kind='matching'):
    return render_template('editor.html',task=task,items=items or [],form=form,activity_types=ACTIVITY_TYPES,initial_kind=initial_kind)


@app.route('/')
def home():
    if teacher_logged_in(): return redirect(url_for('admin'))
    if student_logged_in(): return redirect(url_for('student_dashboard'))
    return render_template('home.html',activity_types=ACTIVITY_TYPES)


@app.route('/register',methods=['GET','POST'])
def register():
    if request.method=='POST':
        name=request.form.get('name','').strip(); email=request.form.get('email','').strip().lower(); p=request.form.get('password',''); p2=request.form.get('password2',''); role=request.form.get('role','student')
        if not name: flash('Аты-жөніңізді енгізіңіз.','error')
        elif not valid_email(email): flash('Email дұрыс енгізілмеген','error')
        elif len(p)<6: flash('Құпиясөз кемінде 6 таңбадан тұруы керек','error')
        elif p!=p2: flash('Құпиясөздер сәйкес келмейді','error')
        elif role not in {'teacher','student'}: flash('Рөлді таңдаңыз.','error')
        else:
            c=db()
            try:
                cur=c.execute('INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)',(name,email,hash_password(p),role)); c.commit(); uid=cur.lastrowid
            except sqlite3.IntegrityError:
                c.close(); flash('Бұл email бұрын тіркелген.','error'); return render_template('register.html')
            c.close(); session.clear(); session.permanent=True; session['user_id']=uid; session['role']=role
            flash('✅ Аккаунт сәтті құрылды!','success'); return redirect(url_for('admin' if role=='teacher' else 'student_dashboard'))
    return render_template('register.html')


@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        email=request.form.get('email','').strip().lower(); password=request.form.get('password','')
        # Keep legacy teacher password login working.
        if not email and secrets.compare_digest(password,ADMIN_PASSWORD):
            session.clear(); session.permanent=True; session['admin']=True; session['role']='teacher'; return redirect(request.args.get('next') or url_for('admin'))
        c=db(); u=c.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone(); c.close()
        if not u or not secrets.compare_digest(u['password_hash'],hash_password(password)):
            flash('Email немесе құпиясөз қате.','error')
        else:
            session.clear(); session.permanent=True; session['user_id']=u['id']; session['role']=u['role']
            return redirect(request.args.get('next') or (url_for('admin') if u['role']=='teacher' else url_for('student_dashboard')))
    return render_template('login.html')


@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('home'))


@app.route('/profile')
def profile():
    if not logged_in(): return redirect(url_for('login'))
    u=current_user()
    if not u: return redirect(url_for('login'))
    c=db(); rc=c.execute('SELECT COUNT(*) n, COALESCE(MAX(CASE WHEN total>0 THEN score*100.0/total ELSE 0 END),0) best FROM results WHERE user_id=?',(u['id'],)).fetchone(); c.close()
    earned,need,pct=level_progress(u['xp']); ach=achievements_for(u['xp'],rc['n'],rc['best'])
    return render_template('profile.html',user=u,level=level_for(u['xp']),earned=earned,need=need,pct=pct,achievements=ach)


@app.post('/profile/update')
def profile_update():
    if not logged_in(): return redirect(url_for('login'))
    u=current_user(); name=request.form.get('name','').strip(); email=request.form.get('email','').strip().lower()
    if not name or not valid_email(email): flash('Аты мен email-ді дұрыс енгізіңіз.','error'); return redirect(url_for('profile'))
    c=db()
    try: c.execute('UPDATE users SET name=?,email=? WHERE id=?',(name,email,u['id'])); c.commit(); flash('✅ Профиль жаңартылды','success')
    except sqlite3.IntegrityError: flash('Бұл email қолданыста.','error')
    c.close(); return redirect(url_for('profile'))


@app.route('/admin')
@role_required('teacher')
def admin():
    owner=teacher_user_id(); c=db()
    where='WHERE t.owner_id=?' if owner else 'WHERE t.owner_id IS NULL'
    params=(owner,) if owner else ()
    tasks=c.execute(f'''SELECT t.*,COUNT(p.id) pair_count,(SELECT COUNT(*) FROM results r WHERE r.task_id=t.id) result_count,
        COALESCE(ROUND(AVG(CASE WHEN r.total>0 THEN r.score*100.0/r.total END),0),0) avg_pct
        FROM tasks t LEFT JOIN pairs p ON p.task_id=t.id LEFT JOIN results r ON r.task_id=t.id {where}
        GROUP BY t.id ORDER BY t.id DESC''',params).fetchall()
    students=c.execute("SELECT COUNT(*) n FROM users WHERE role='student'").fetchone()['n']
    avg=c.execute('SELECT COALESCE(AVG(score*100.0/total),0) a FROM results WHERE total>0').fetchone()['a']
    active=c.execute("SELECT COUNT(*) n FROM live_games WHERE status='lobby'").fetchone()['n']
    c.close(); return render_template('admin.html',tasks=tasks,activity_types=ACTIVITY_TYPES,students=students,avg_pct=round(avg),active_games=active,user=current_user())


@app.route('/admin/new',methods=['GET','POST'])
@role_required('teacher')
def new_task():
    if request.method=='POST':
        title=request.form.get('title','').strip(); kind=activity_type(request.form); items=collect_items(request.form,kind); difficulty,timer,shuffle=clean_settings(request.form)
        if not title or not items: flash('Атауы мен кемінде бір дұрыс толтырылған тапсырма енгізіңіз.','error'); return editor_context(request.form,None,items,kind)
        c=db(); slug=secrets.token_urlsafe(7)
        while c.execute('SELECT 1 FROM tasks WHERE slug=?',(slug,)).fetchone(): slug=secrets.token_urlsafe(7)
        save_task(c,title,slug,difficulty,timer,shuffle,kind,items,teacher_user_id()); c.commit(); c.close(); flash('✅ Тапсырма сәтті жарияланды','success'); return redirect(url_for('admin'))
    initial=request.args.get('type','matching'); initial=initial if initial in ACTIVITY_TYPES else 'matching'
    initial_items={'left':'','right':''} if initial=='matching' else {}
    return editor_context(None,None,[initial_items],initial)


@app.route('/admin/edit/<int:task_id>',methods=['GET','POST'])
@role_required('teacher')
def edit_task(task_id):
    c=db(); task=c.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
    if not task: c.close(); abort(404)
    if task['owner_id'] and teacher_user_id() and task['owner_id']!=teacher_user_id(): c.close(); abort(403)
    kind=task['activity_type']
    if request.method=='POST':
        title=request.form.get('title','').strip(); kind=activity_type(request.form); items=collect_items(request.form,kind); difficulty,timer,shuffle=clean_settings(request.form)
        if not title or not items: c.close(); flash('Атауы мен кемінде бір дұрыс толтырылған тапсырма енгізіңіз.','error'); return editor_context(request.form,task,items,kind)
        c.execute('UPDATE tasks SET title=?,difficulty=?,timer_seconds=?,shuffle=?,activity_type=?,data_json=?,owner_id=? WHERE id=?',(title,difficulty,timer,shuffle,kind,json.dumps(items,ensure_ascii=False),teacher_user_id(),task_id)); c.execute('DELETE FROM pairs WHERE task_id=?',(task_id,))
        if kind=='matching': c.executemany('INSERT INTO pairs(task_id,left_text,right_text) VALUES(?,?,?)',[(task_id,x['left'],x['right']) for x in items])
        c.commit(); c.close(); flash('✅ Өзгерістер сақталды','success'); return redirect(url_for('admin'))
    try: items=json.loads(task['data_json'] or '[]')
    except Exception: items=[]
    if not items and kind=='matching': items=[dict(x) for x in c.execute('SELECT left_text as left,right_text as right FROM pairs WHERE task_id=? ORDER BY id',(task_id,)).fetchall()]
    c.close(); return editor_context(None,task,items,kind)


@app.post('/admin/delete/<int:task_id>')
@role_required('teacher')
def delete_task(task_id):
    c=db(); c.execute('DELETE FROM results WHERE task_id=?',(task_id,)); c.execute('DELETE FROM pairs WHERE task_id=?',(task_id,)); c.execute('DELETE FROM tasks WHERE id=?',(task_id,)); c.commit(); c.close(); flash('Тапсырма өшірілді.','success'); return redirect(url_for('admin'))


@app.route('/admin/results/<int:task_id>')
@role_required('teacher')
def results(task_id):
    c=db(); task=c.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone(); rows=c.execute('SELECT * FROM results WHERE task_id=? ORDER BY score DESC,time_seconds ASC,id DESC',(task_id,)).fetchall()
    if not task: c.close(); abort(404)
    c.close(); difficult=max(0,len(rows)); avg=round(sum((r['score']/r['total']*100 if r['total'] else 0) for r in rows)/difficult) if difficult else 0
    return render_template('results.html',task=task,results=rows,avg_pct=avg)


@app.route('/task/<slug>')
def student(slug):
    c=db(); task=c.execute('SELECT * FROM tasks WHERE slug=?',(slug,)).fetchone()
    if not task: c.close(); abort(404)
    try: items=json.loads(task['data_json'] or '[]')
    except Exception: items=[]
    if task['activity_type']=='matching' and not items: items=[dict(x) for x in c.execute('SELECT id,left_text as left,right_text as right FROM pairs WHERE task_id=? ORDER BY id',(task['id'],)).fetchall()]
    c.close(); return render_template('student.html',task=task,items=items,activity_types=ACTIVITY_TYPES,user=current_user())


@app.route('/student')
@role_required('student')
def student_dashboard():
    u=current_user(); c=db(); tasks=c.execute('SELECT t.*,COUNT(r.id) result_count FROM tasks t LEFT JOIN results r ON r.task_id=t.id GROUP BY t.id ORDER BY t.id DESC').fetchall(); rows=c.execute('SELECT * FROM results WHERE user_id=? ORDER BY id DESC LIMIT 10',(u['id'],)).fetchall(); leaders=c.execute("SELECT name,xp FROM users WHERE role='student' ORDER BY xp DESC,id ASC LIMIT 10").fetchall(); count=c.execute('SELECT COUNT(*) n FROM results WHERE user_id=?',(u['id'],)).fetchone()['n']; best=c.execute('SELECT COALESCE(MAX(score*100.0/total),0) b FROM results WHERE user_id=? AND total>0',(u['id'],)).fetchone()['b']; c.close(); earned,need,pct=level_progress(u['xp']); return render_template('student_dashboard.html',user=u,tasks=tasks,recent=rows,leaders=leaders,level=level_for(u['xp']),earned=earned,need=need,pct=pct,achievements=achievements_for(u['xp'],count,best))


@app.get('/leaderboard')
def leaderboard():
    c=db(); rows=c.execute("SELECT name,xp FROM users WHERE role='student' ORDER BY xp DESC,id ASC LIMIT 50").fetchall(); c.close(); return render_template('leaderboard.html',leaders=rows,user=current_user())


@app.post('/task/<slug>/submit')
def submit(slug):
    data=request.get_json(silent=True) or {}; name=(data.get('student_name') or (current_user()['name'] if current_user() else 'Аноним')).strip()[:80] or 'Аноним'
    try: elapsed=max(0,min(86400,int(data.get('time_seconds',0))))
    except: elapsed=0
    c=db(); task=c.execute('SELECT * FROM tasks WHERE slug=?',(slug,)).fetchone()
    if not task: c.close(); return jsonify({'error':'Тапсырма табылмады'}),404
    try: items=json.loads(task['data_json'] or '[]')
    except: items=[]
    if task['activity_type']=='matching' and not items: items=[{'left':x['left_text'],'right':x['right_text']} for x in c.execute('SELECT * FROM pairs WHERE task_id=?',(task['id'],)).fetchall()]
    answers=data.get('answers',{}) or {}; score=0; kind=task['activity_type']
    for i,item in enumerate(items):
        a=answers.get(str(i),'')
        if kind=='matching': ok=str(a)==str(i)
        elif kind in {'quiz','imagequiz','audioquiz','categorize'}: ok=str(a).strip()==str(item.get('correct','')).strip()
        elif kind=='ordering': ok=isinstance(a,list) and a==item.get('order',[])
        elif kind=='flashcards': ok=str(a)=='known'
        else: ok=str(a).strip().casefold()==str(item.get('answer','')).strip().casefold()
        score += 1 if ok else 0
    total=len(items); pct=round(score*100/total) if total else 0; xp=score*100 + (50 if total and pct>=80 and elapsed and elapsed <= max(20,total*8) else 0)
    u=current_user(); uid=u['id'] if u and u['role']=='student' else None
    c.execute('INSERT INTO results(task_id,student_name,score,total,time_seconds,user_id,xp_earned) VALUES(?,?,?,?,?,?,?)',(task['id'],name,score,total,elapsed,uid,xp))
    if uid: c.execute('UPDATE users SET xp=xp+? WHERE id=?',(xp,uid))
    c.commit(); c.close(); return jsonify({'score':score,'total':total,'student_name':name,'percentage':pct,'xp':xp})


@app.post('/api/draft')
@role_required('teacher')
def draft_save():
    data=request.get_json(silent=True) or {}; task_id=data.get('task_id'); payload=json.dumps(data.get('payload',{}),ensure_ascii=False); uid=teacher_user_id(); c=db()
    c.execute('INSERT INTO drafts(user_id,task_id,payload_json) VALUES(?,?,?) ON CONFLICT(user_id,task_id) DO UPDATE SET payload_json=excluded.payload_json,updated_at=CURRENT_TIMESTAMP',(uid,task_id,payload)); c.commit(); c.close(); return jsonify({'ok':True,'message':'✓ Автоматты сақталды'})


@app.post('/admin/live/<int:task_id>')
@role_required('teacher')
def live_create(task_id):
    c=db(); task=c.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
    if not task: c.close(); return jsonify({'error':'Тапсырма табылмады'}),404
    pin=f'{secrets.randbelow(900000)+100000}';
    while c.execute('SELECT 1 FROM live_games WHERE pin=?',(pin,)).fetchone(): pin=f'{secrets.randbelow(900000)+100000}'
    cur=c.execute('INSERT INTO live_games(task_id,teacher_id,pin) VALUES(?,?,?)',(task_id,teacher_user_id(),pin)); c.commit(); gid=cur.lastrowid; c.close(); return jsonify({'ok':True,'pin':pin,'game_id':gid})


@app.get('/live/<int:game_id>')
def live(game_id):
    c=db(); g=c.execute('SELECT g.*,t.title FROM live_games g JOIN tasks t ON t.id=g.task_id WHERE g.id=?',(game_id,)).fetchone(); c.close()
    if not g: abort(404)
    return render_template('live.html',game=g,user=current_user())


@app.post('/live/join')
def live_join():
    pin=request.form.get('pin','').strip(); c=db(); g=c.execute("SELECT * FROM live_games WHERE pin=? AND status='lobby'",(pin,)).fetchone(); c.close()
    if not g: flash('PIN табылмады немесе ойын аяқталған.','error'); return redirect(url_for('home'))
    return redirect(url_for('live',game_id=g['id']))


@app.context_processor
def inject():
    u=current_user(); return {'logged_in':logged_in(),'teacher_logged_in':teacher_logged_in(),'student_logged_in':student_logged_in(),'current_user':u,'activity_types':ACTIVITY_TYPES,'level_for':level_for}

init_db()
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)),debug=True)

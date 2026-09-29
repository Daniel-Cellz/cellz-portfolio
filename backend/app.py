import os, sys, uuid
from pathlib import Path
from functools import wraps
import psycopg2, psycopg2.extras
from dotenv import load_dotenv
from flask import Flask, request, jsonify, session, send_from_directory, redirect
from werkzeug.exceptions import HTTPException
from werkzeug.security import generate_password_hash, check_password_hash

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                      # the "Cellz Creative portfolio" folder
load_dotenv(HERE / '.env')
UPLOADS = ROOT / 'uploads'
UPLOADS.mkdir(exist_ok=True)

app = Flask(__name__, static_folder=None)
app.secret_key = os.getenv('SECRET_KEY', 'change-me')
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024   # 500 MB per request

IMG = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
VID = {'mp4', 'webm', 'mov', 'm4v'}

# ---------- database helper ----------
def q(sql, args=(), one=False):
    con = psycopg2.connect(os.getenv('DATABASE_URL'))
    try:
        with con, con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, args)
            if cur.description:
                rows = cur.fetchall()
                return (rows[0] if rows else None) if one else rows
    finally:
        con.close()

def save_file(f, allowed):
    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
    if ext not in allowed:
        from werkzeug.exceptions import BadRequest
        raise BadRequest('Unsupported file type: .' + ext)
    name = f'{uuid.uuid4().hex}.{ext}'
    f.save(UPLOADS / name)
    return name, ('video' if ext in VID else 'image')

def rm_file(name):
    try: (UPLOADS / name).unlink()
    except FileNotFoundError: pass

def auth(fn):
    @wraps(fn)
    def w(*a, **k):
        if not session.get('admin'):
            return jsonify(error='Please log in'), 401
        return fn(*a, **k)
    return w

@app.errorhandler(HTTPException)
def http_err(e):
    if request.path.startswith('/api'):
        return jsonify(error=e.description), e.code
    return e

# ---------- pages & static files ----------
@app.get('/')
def home(): return send_from_directory(ROOT, 'landingpage.html')
@app.get('/site-connector.js')
def connector(): return send_from_directory(ROOT, 'site-connector.js')
@app.get('/admin')
def admin_login():
    if session.get('admin'): return redirect('/admin/dashboard')
    return send_from_directory(ROOT / 'admin', 'login.html')
@app.get('/admin/dashboard')
def admin_dash():
    if not session.get('admin'): return redirect('/admin')
    return send_from_directory(ROOT / 'admin', 'dashboard.html')
@app.get('/uploads/<path:n>')
def up_file(n): return send_from_directory(UPLOADS, n)
@app.get('/IMAGE/<path:n>')
def img_file(n): return send_from_directory(ROOT / 'IMAGE', n)
@app.get('/VIDEO/<path:n>')
def vid_file(n): return send_from_directory(ROOT / 'VIDEO', n)

# ---------- public API (used by the landing page) ----------
@app.get('/api/public')
def public():
    site = q("SELECT kind, media_type, '/uploads/'||file_path AS url FROM site_media ORDER BY sort_order, id")
    return jsonify(
        sectors=q('SELECT id, name FROM sectors ORDER BY sort_order, id'),
        brands=q('SELECT id, name FROM brands ORDER BY name'),
        items=q("""SELECT c.id, c.title, c.sector_id, c.brand_id, b.name AS brand, c.media_type,
                   '/uploads/'||c.file_path AS url
                   FROM creatives c JOIN brands b ON b.id=c.brand_id ORDER BY c.created_at DESC"""),
        hero=next((s for s in site if s['kind'] == 'hero'), None),
        slider=[s for s in site if s['kind'] == 'slider'])

@app.post('/api/visit')
def visit():
    q("""INSERT INTO daily_visits(day, visits) VALUES (CURRENT_DATE, 1)
         ON CONFLICT (day) DO UPDATE SET visits = daily_visits.visits + 1""")
    return '', 204

@app.post('/api/track')
def track():
    d = request.get_json(silent=True, force=True) or {}
    for i, s in (d.get('seconds') or {}).items():
        q('UPDATE creatives SET view_seconds = view_seconds + %s WHERE id = %s', (max(0, min(int(s), 3600)), int(i)))
    for i, n in (d.get('views') or {}).items():
        q('UPDATE creatives SET view_count = view_count + %s WHERE id = %s', (max(0, min(int(n), 100)), int(i)))
    return '', 204

# ---------- admin auth ----------
@app.post('/api/admin/login')
def login():
    d = request.get_json(silent=True) or {}
    u = q('SELECT * FROM admins WHERE username=%s', (d.get('username', '').strip(),), one=True)
    if u and check_password_hash(u['password_hash'], d.get('password', '')):
        session['admin'] = u['id']
        return jsonify(ok=True)
    return jsonify(error='Invalid username or password'), 401

@app.post('/api/admin/logout')
def logout():
    session.clear()
    return jsonify(ok=True)

@app.post('/api/admin/password')
@auth
def change_password():
    d = request.get_json(silent=True) or {}
    u = q('SELECT * FROM admins WHERE id=%s', (session['admin'],), one=True)
    if not check_password_hash(u['password_hash'], d.get('current', '')):
        return jsonify(error='Current password is wrong'), 400
    if len(d.get('new', '')) < 6:
        return jsonify(error='New password must be at least 6 characters'), 400
    q('UPDATE admins SET password_hash=%s WHERE id=%s', (generate_password_hash(d['new']), u['id']))
    return jsonify(ok=True)

# ---------- analytics ----------
@app.get('/api/admin/stats')
@auth
def stats():
    def grp(table, col):
        return q(f"""SELECT t.name, COUNT(c.id) AS works, COALESCE(SUM(c.view_seconds),0) AS seconds
                     FROM {table} t LEFT JOIN creatives c ON c.{col}=t.id GROUP BY t.id ORDER BY seconds DESC""")
    return jsonify(
        visits=q("""SELECT COALESCE(SUM(visits),0) AS total,
                    COALESCE(SUM(visits) FILTER (WHERE day=CURRENT_DATE),0) AS today FROM daily_visits""", one=True),
        totals=q("SELECT COALESCE(SUM(view_count),0) AS views, COALESCE(SUM(view_seconds),0) AS seconds, COUNT(*) AS works FROM creatives", one=True),
        days=q("""SELECT to_char(g,'YYYY-MM-DD') AS day, COALESCE(v.visits,0) AS visits
                  FROM generate_series(CURRENT_DATE-13, CURRENT_DATE, '1 day') g
                  LEFT JOIN daily_visits v ON v.day=g ORDER BY g"""),
        top=q("""SELECT c.id, c.title, c.media_type, '/uploads/'||c.file_path AS url, c.view_count, c.view_seconds,
                 s.name AS sector, b.name AS brand FROM creatives c
                 JOIN sectors s ON s.id=c.sector_id JOIN brands b ON b.id=c.brand_id
                 ORDER BY c.view_seconds DESC, c.view_count DESC LIMIT 10"""),
        by_sector=grp('sectors', 'sector_id'), by_brand=grp('brands', 'brand_id'))

# ---------- sectors (skill roles) & brands ----------
COL = {'sectors': 'sector_id', 'brands': 'brand_id'}

@app.get('/api/admin/list/<kind>')
@auth
def list_get(kind):
    if kind not in COL: return jsonify(error='Not found'), 404
    return jsonify(q(f"""SELECT t.id, t.name, COUNT(c.id) AS works FROM {kind} t
                         LEFT JOIN creatives c ON c.{COL[kind]}=t.id GROUP BY t.id ORDER BY t.id"""))

@app.post('/api/admin/list/<kind>')
@auth
def list_add(kind):
    if kind not in COL: return jsonify(error='Not found'), 404
    name = (request.get_json(silent=True) or {}).get('name', '').strip()
    if not name: return jsonify(error='Name is required'), 400
    r = q(f'INSERT INTO {kind}(name) VALUES (%s) ON CONFLICT (name) DO NOTHING RETURNING id', (name,), one=True)
    if not r: return jsonify(error='That name already exists'), 400
    return jsonify(id=r['id'], name=name)

@app.put('/api/admin/list/<kind>/<int:i>')
@auth
def list_rename(kind, i):
    if kind not in COL: return jsonify(error='Not found'), 404
    name = (request.get_json(silent=True) or {}).get('name', '').strip()
    if not name: return jsonify(error='Name is required'), 400
    try: q(f'UPDATE {kind} SET name=%s WHERE id=%s', (name, i))
    except psycopg2.errors.UniqueViolation: return jsonify(error='That name already exists'), 400
    return jsonify(ok=True)

@app.delete('/api/admin/list/<kind>/<int:i>')
@auth
def list_del(kind, i):
    if kind not in COL: return jsonify(error='Not found'), 404
    try: q(f'DELETE FROM {kind} WHERE id=%s', (i,))
    except psycopg2.errors.ForeignKeyViolation:
        return jsonify(error='Move or delete the creatives using this first'), 400
    return jsonify(ok=True)

# ---------- creatives ----------
@app.get('/api/admin/creatives')
@auth
def cr_list():
    return jsonify(q("""SELECT c.id, c.title, c.sector_id, c.brand_id, c.media_type, '/uploads/'||c.file_path AS url,
                        c.view_count, c.view_seconds FROM creatives c ORDER BY c.created_at DESC"""))

@app.post('/api/admin/creatives')
@auth
def cr_add():
    f = request.files.get('file')
    title = request.form.get('title', '').strip()
    if not f or not title: return jsonify(error='File and title are required'), 400
    name, t = save_file(f, IMG | VID)
    q("INSERT INTO creatives(title, sector_id, brand_id, media_type, file_path) VALUES (%s,%s,%s,%s,%s)",
      (title, int(request.form['sector_id']), int(request.form['brand_id']), t, name))
    return jsonify(ok=True)

@app.put('/api/admin/creatives/<int:i>')
@auth
def cr_edit(i):
    d = request.get_json(silent=True) or {}
    q('UPDATE creatives SET title=%s, sector_id=%s, brand_id=%s WHERE id=%s',
      (d['title'], int(d['sector_id']), int(d['brand_id']), i))
    return jsonify(ok=True)

@app.delete('/api/admin/creatives/<int:i>')
@auth
def cr_del(i):
    r = q('DELETE FROM creatives WHERE id=%s RETURNING file_path', (i,), one=True)
    if r: rm_file(r['file_path'])
    return jsonify(ok=True)

# ---------- hero video & about slider ----------
@app.get('/api/admin/site')
@auth
def site_get():
    return jsonify(q("SELECT id, kind, media_type, '/uploads/'||file_path AS url FROM site_media ORDER BY sort_order, id"))

@app.post('/api/admin/site/hero')
@auth
def hero_set():
    f = request.files.get('file')
    if not f: return jsonify(error='Choose a video'), 400
    name, t = save_file(f, VID)
    for r in q("DELETE FROM site_media WHERE kind='hero' RETURNING file_path"): rm_file(r['file_path'])
    q("INSERT INTO site_media(kind, media_type, file_path) VALUES ('hero', %s, %s)", (t, name))
    return jsonify(ok=True)

@app.post('/api/admin/site/slider')
@auth
def slider_add():
    for f in request.files.getlist('files'):
        name, t = save_file(f, IMG)
        q("INSERT INTO site_media(kind, media_type, file_path, sort_order) VALUES ('slider', %s, %s, (SELECT COALESCE(MAX(sort_order),0)+1 FROM site_media))", (t, name))
    return jsonify(ok=True)

@app.delete('/api/admin/site/<int:i>')
@auth
def site_del(i):
    r = q('DELETE FROM site_media WHERE id=%s RETURNING file_path', (i,), one=True)
    if r: rm_file(r['file_path'])
    return jsonify(ok=True)

# ---------- run ----------
if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'create-admin':
        import getpass
        u = input('Admin username: ').strip()
        p = getpass.getpass('Admin password: ')
        q("""INSERT INTO admins(username, password_hash) VALUES (%s,%s)
             ON CONFLICT (username) DO UPDATE SET password_hash=EXCLUDED.password_hash""",
          (u, generate_password_hash(p)))
        print('Admin saved. You can now log in at http://localhost:5000/admin')
    else:
        app.run(debug=True, port=5000)

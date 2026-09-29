import os, sys, uuid, re, json, time
import urllib.request, urllib.error
from html import escape
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

# Where do uploaded files live?
#  - If SUPABASE_URL and SUPABASE_SECRET_KEY are set  -> in your Supabase Storage bucket (online)
#  - Otherwise                                          -> in the local "uploads" folder (your PC)
SB_URL = (os.getenv('SUPABASE_URL') or '').rstrip('/')
SB_KEY = os.getenv('SUPABASE_SECRET_KEY') or ''
SB_BUCKET = os.getenv('SUPABASE_BUCKET') or 'uploads'
REMOTE = bool(SB_URL and SB_KEY)
PFX = f'{SB_URL}/storage/v1/object/public/{SB_BUCKET}/' if REMOTE else '/uploads/'

app = Flask(__name__, static_folder=None)
app.secret_key = os.getenv('SECRET_KEY', 'change-me')
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024   # 500 MB per request
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                  SESSION_COOKIE_SECURE=os.getenv('PRODUCTION') == '1')   # PRODUCTION=1 is set on the live site only

IMG = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
VID = {'mp4', 'webm', 'mov', 'm4v'}

# ---------- database helper ----------
def q(sql, args=(), one=False):
    sql = sql.replace("'/uploads/'", "'" + PFX + "'")   # file addresses point to the right place
    con = psycopg2.connect(os.getenv('DATABASE_URL'))
    try:
        with con, con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, args)
            if cur.description:
                rows = cur.fetchall()
                return (rows[0] if rows else None) if one else rows
    finally:
        con.close()

def sb_call(method, name, body=None, ctype=None):
    req = urllib.request.Request(f'{SB_URL}/storage/v1/object/{SB_BUCKET}/{name}', data=body, method=method,
        headers={'Authorization': 'Bearer ' + SB_KEY, 'apikey': SB_KEY,
                 'Content-Type': ctype or 'application/octet-stream', 'User-Agent': 'cellz-portfolio/1.0'})
    return urllib.request.urlopen(req, timeout=120)

def save_file(f, allowed):
    from werkzeug.exceptions import BadRequest
    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
    if ext not in allowed:
        raise BadRequest('Unsupported file type: .' + ext)
    name = f'{uuid.uuid4().hex}.{ext}'
    if REMOTE:
        data = f.read()
        if len(data) > 50 * 1024 * 1024:
            raise BadRequest('This file is over 50 MB, the free storage limit. Please compress it and try again.')
        try:
            sb_call('POST', name, data, f.mimetype)
        except urllib.error.HTTPError as e:
            print('Supabase upload error', e.code, e.read().decode())
            raise BadRequest('Upload to storage failed. Check the server log for the reason.')
        except Exception as e:
            print('Supabase upload error', e)
            raise BadRequest('Upload to storage failed. Check the server log for the reason.')
    else:
        f.save(UPLOADS / name)
    return name, ('video' if ext in VID else 'image')

def rm_file(name):
    if REMOTE:
        try: sb_call('DELETE', name)
        except Exception as e: print('Supabase delete error', e)
        return
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

# ---------- contact form -> Resend ----------
RATE = {}   # simple spam guard: max 5 messages per hour per visitor

@app.post('/api/contact')
def contact():
    d = request.get_json(silent=True) or {}
    if d.get('website'):                       # hidden trap field: bots fill it in
        return jsonify(ok=True)
    ip = request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()
    now = time.time()
    RATE[ip] = [t for t in RATE.get(ip, []) if now - t < 3600]
    if len(RATE[ip]) >= 5:
        return jsonify(error='Too many messages. Please try again later.'), 429
    name = (d.get('name') or '').strip()[:100]
    email = (d.get('email') or '').strip()[:200]
    subject = re.sub(r'[\r\n]+', ' ', (d.get('subject') or 'General enquiry').strip())[:100]
    message = (d.get('message') or '').strip()[:5000]
    if not name or not message or not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        return jsonify(error='Please fill in your name, a valid email and a message.'), 400
    key, to = os.getenv('RESEND_API_KEY'), os.getenv('CONTACT_TO_EMAIL')
    if not key or not to:
        return jsonify(error='Email is not configured yet.'), 500
    payload = {
        'from': os.getenv('CONTACT_FROM_EMAIL', 'Cellz Portfolio <onboarding@resend.dev>'),
        'to': [to],
        'reply_to': email,                      # hitting Reply answers the visitor directly
        'subject': f'New enquiry: {subject} - {name}',
        'html': f'<p><b>Name:</b> {escape(name)}<br><b>Email:</b> {escape(email)}<br>'
                f'<b>Category:</b> {escape(subject)}</p><p>{escape(message).replace(chr(10), "<br>")}</p>',
    }
    req = urllib.request.Request('https://api.resend.com/emails', data=json.dumps(payload).encode(), method='POST',
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json', 'User-Agent': 'cellz-portfolio/1.0'})
    try:
        urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as e:
        print('Resend error', e.code, e.read().decode())      # shows the reason in your terminal
        return jsonify(error='Your message could not be sent. Please try again.'), 502
    except Exception as e:
        print('Resend error', e)
        return jsonify(error='Your message could not be sent. Please try again.'), 502
    RATE[ip].append(now)
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

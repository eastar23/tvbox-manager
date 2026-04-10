import os
import sqlite3
import json
import secrets
import concurrent.futures
import requests
from functools import wraps
from flask import Flask, request, session, redirect, url_for, render_template, jsonify, Response
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
# 适配反向代理，处理 X-Forwarded-Proto 等头部
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

# --- Configuration & Constants ---
APP_VERSION = "v1.0.25"
app.secret_key = os.environ.get('SECRET_KEY', 'super-secret-starlink-clone-key')
DATABASE = os.environ.get('DB_PATH', '/app/data/database.db')
REG_CODE = os.environ.get('REG_CODE', '888888')
BASE_URL = os.environ.get('BASE_URL', '').rstrip('/')
HTTP_TIMEOUT = 8

# 全局 HTTP 会话
http_session = requests.Session()
http_session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
})

# --- Database Layer ---
def get_db():
    conn = sqlite3.connect(DATABASE, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """初始化数据库并建立索引"""
    with get_db() as db:
        # 用户表
        db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_admin INTEGER DEFAULT 0
            )
        ''')
        
        # 接口数据表
        db.execute('''
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                type TEXT DEFAULT 'site',
                status TEXT DEFAULT 'unknown',
                order_index INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # 系统设置表
        db.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')

        # 建立索引以提升大规模数据下的性能
        db.execute('CREATE INDEX IF NOT EXISTS idx_sources_user ON sources(user_id)')
        db.execute('CREATE INDEX IF NOT EXISTS idx_sources_url ON sources(url)')
        db.execute('CREATE INDEX IF NOT EXISTS idx_sources_order ON sources(order_index)')

        # 初始化默认配置
        db.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', ('invite_code', REG_CODE))
        db.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', ('webhook_token', secrets.token_hex(16)))
        
        db.commit()

# Ensure DB is initialized
init_db()

# --- Helpers & Decorators ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'):
            if request.path.startswith('/api/'):
                return jsonify({'status': 'error', 'message': '需要管理员权限'}), 403
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def jsonify_success(message='操作成功', **kwargs):
    return jsonify({'status': 'success', 'message': message, **kwargs})

def jsonify_error(message='操作失败', code=200):
    return jsonify({'status': 'error', 'message': message}), code

def parse_aggregate_source(url):
    """尝试解析并解构多仓 JSON"""
    try:
        # 只针对可能是 JSON 的 URL 进行尝试
        if not ('urls' in url or url.endswith('.json')):
            return None
            
        r = http_session.get(url, timeout=HTTP_TIMEOUT, verify=False)
        if r.status_code != 200:
            return None
            
        content = r.text.strip()
        # 兼容性处理：剔除特殊注释
        if content.startswith('//'):
            content = '\n'.join([l for l in content.split('\n') if not l.strip().startswith('//')])

        json_data = json.loads(content)
        if isinstance(json_data, dict) and "urls" in json_data and isinstance(json_data["urls"], list):
            return json_data["urls"]
    except:
        pass
    return None

@app.context_processor
def inject_version():
    return dict(version=APP_VERSION)

# --- Frontend Routes ---
@app.route('/')
def index():
    return redirect(url_for('dashboard') if 'user_id' in session else url_for('login'))

@app.route('/login')
def login():
    if 'user_id' in session: return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/register')
def register():
    if 'user_id' in session: return redirect(url_for('dashboard'))
    return render_template('register.html')

@app.route('/dashboard')
@login_required
def dashboard():
    username = session.get('username')
    is_admin = session.get('is_admin', False)
    host_url = BASE_URL if BASE_URL else request.host_url.rstrip('/')
    sub_url = host_url + url_for('get_tvbox_json', username=username)
    return render_template('dashboard.html', username=username, sub_url=sub_url, is_admin=is_admin)

@app.route('/admin')
@admin_required
def admin_dashboard():
    with get_db() as db:
        invite_code = db.execute("SELECT value FROM settings WHERE key = 'invite_code'").fetchone()['value']
        webhook_token = db.execute("SELECT value FROM settings WHERE key = 'webhook_token'").fetchone()['value']
    return render_template('admin.html', is_admin=True, invite_code=invite_code, webhook_token=webhook_token)

# --- Auth APIs ---
@app.route('/api/auth/register', methods=['POST'])
def api_register():
    data = request.json
    username, password, invite_code = data.get('username', '').strip(), data.get('password', ''), data.get('invite_code', '').strip()

    if not username or not password: return jsonify_error('用户名和密码不能为空')

    with get_db() as db:
        expected_code = db.execute("SELECT value FROM settings WHERE key = 'invite_code'").fetchone()['value']
        if invite_code != expected_code: return jsonify_error('邀请码错误')

        try:
            user_count = db.execute("SELECT COUNT(id) as c FROM users").fetchone()['c']
            is_admin = 1 if user_count == 0 else 0
            db.execute('INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)', 
                       (username, generate_password_hash(password, method='pbkdf2:sha256'), is_admin))
            db.commit()
            return jsonify_success('注册成功')
        except sqlite3.IntegrityError:
            return jsonify_error('用户名已存在')

@app.route('/api/auth/login', methods=['POST'])
def api_login():
    data = request.json
    username, password = data.get('username', '').strip(), data.get('password', '')

    with get_db() as db:
        user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        
    if user and check_password_hash(user['password_hash'], password):
        session.update({'user_id': user['id'], 'username': user['username'], 'is_admin': user['is_admin'] == 1})
        return jsonify_success('登录成功')
    return jsonify_error('用户名或密码错误')

@app.route('/api/auth/logout')
def api_logout():
    session.clear()
    return redirect(url_for('login'))

# --- Source Management APIs ---
@app.route('/api/source/list')
@login_required
def api_source_list():
    with get_db() as db:
        sources = db.execute('SELECT * FROM sources WHERE user_id = ? ORDER BY order_index ASC, id ASC', (session['user_id'],)).fetchall()
        return jsonify_success(data=[dict(row) for row in sources])

@app.route('/api/source/add', methods=['POST'])
@login_required
def api_source_add():
    user_id = session['user_id']
    data = request.json
    name, url, stype = data.get('name', '').strip(), data.get('url', '').strip(), data.get('type', 'site')

    if not name or not url: return jsonify_error('名称和 URL 不能为空')

    # 1. 尝试作为多仓 JSON 解析
    aggregate_urls = parse_aggregate_source(url)
    if aggregate_urls:
        added = 0
        with get_db() as db:
            existens = {row['url'] for row in db.execute('SELECT url FROM sources WHERE user_id = ?', (user_id,)).fetchall()}
            for entry in aggregate_urls:
                e_url = entry.get('url', '').strip()
                if e_url and e_url not in existens:
                    db.execute('INSERT INTO sources (user_id, name, url, type) VALUES (?, ?, ?, ?)', 
                               (user_id, entry.get('name', '未命名'), e_url, stype))
                    existens.add(e_url)
                    added += 1
            db.commit()
        return jsonify_success(f'成功导入 {added} 个聚合接口')

    # 2. 单个添加模式
    with get_db() as db:
        if db.execute('SELECT id FROM sources WHERE user_id = ? AND url = ?', (user_id, url)).fetchone():
            return jsonify_error('该接口已在您的列表中')
        db.execute('INSERT INTO sources (user_id, name, url, type) VALUES (?, ?, ?, ?)', (user_id, name, url, stype))
        db.commit()
    return jsonify_success('添加成功')

@app.route('/api/source/batch_add', methods=['POST'])
@login_required
def api_source_batch_add():
    user_id, items = session['user_id'], request.json.get('items', [])
    if not items: return jsonify_error('未选择任何接口')
    
    with get_db() as db:
        max_order = (db.execute('SELECT MAX(order_index) FROM sources WHERE user_id = ?', (user_id,)).fetchone()[0] or 0)
        for i, item in enumerate(items):
            link = item.get('link') or item.get('url')
            if link:
                db.execute('INSERT INTO sources (user_id, name, url, type, order_index) VALUES (?, ?, ?, ?, ?)', 
                           (user_id, item.get('name', '未命名'), link, 'site', max_order + i + 1))
        db.commit()
    return jsonify_success(f'成功批量添加 {len(items)} 个接口')

@app.route('/api/source/update', methods=['POST'])
@login_required
def api_source_update():
    data = request.json
    sid, name, url, stype = data.get('id'), data.get('name', '').strip(), data.get('url', '').strip(), data.get('type', 'site')
    if not sid or not name or not url: return jsonify_error('参数不全')

    with get_db() as db:
        db.execute('UPDATE sources SET name = ?, url = ?, type = ? WHERE id = ? AND user_id = ?', 
                   (name, url, stype, sid, session['user_id']))
        db.commit()
    return jsonify_success('保存成功')

@app.route('/api/source/delete', methods=['POST'])
@login_required
def api_source_delete():
    source_id = request.json.get('id')
    with get_db() as db:
        db.execute('DELETE FROM sources WHERE id = ? AND user_id = ?', (source_id, session['user_id']))
        db.commit()
    return jsonify_success('删除成功')

@app.route('/api/source/reorder', methods=['POST'])
@login_required
def api_source_reorder():
    order_data = request.json.get('order', [])
    with get_db() as db:
        for idx, sid in enumerate(order_data):
            db.execute('UPDATE sources SET order_index = ? WHERE id = ? AND user_id = ?', (idx, sid, session['user_id']))
        db.commit()
    return jsonify_success('排序已保存')

@app.route('/api/source/check', methods=['POST'])
@login_required
def api_source_check():
    url, sid = request.json.get('url'), request.json.get('id')
    if not url: return jsonify_error('URL missing')
    try:
        r = http_session.get(url, timeout=5, stream=True)
        r.close()
        status = 'online' if r.status_code < 400 else 'offline'
        if sid:
            with get_db() as db:
                db.execute('UPDATE sources SET status = ? WHERE id = ? AND user_id = ?', (status, sid, session['user_id']))
                db.commit()
        return jsonify_success(status=status, code=r.status_code)
    except Exception as e:
        if sid:
            with get_db() as db:
                db.execute('UPDATE sources SET status = ? WHERE id = ? AND user_id = ?', ('offline', sid, session['user_id']))
                db.commit()
        return jsonify_error(str(e))

# --- Recommendation & External APIs ---
@app.route('/api/external/aipan')
@login_required
def api_external_aipan():
    combined_list = []
    # 1. 本地推荐 (Webhook 注入)
    for path in ['/app/data/recommended.json', 'data/recommended.json']:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    combined_list.extend(json.load(f).get('list', []))
            except: pass
            break
    
    # 2. 爱盼接口推荐
    try:
        r = http_session.get('https://www.aipan.me/api/tvbox', timeout=5, verify=False)
        if r.status_code == 200: combined_list.extend(r.json().get('list', []))
    except: pass

    # 3. 兜底列表
    if not combined_list:
        combined_list = [
            {"name": "🌟 饭太硬", "link": "http://饭太硬.top/tv"},
            {"name": "🐱 肥猫", "link": "http://肥猫.com"},
            {"name": "🐉 道长", "link": "https://pastebin.com/raw/5NHaxyO7"},
            {"name": "💨 南风", "link": "https://m3u8.xn--nwy97m.cn/nanfeng/lite.json"},
            {"name": "📦 荷城茶秀", "link": "http://rihou.cc:88/荷城茶秀"},
            {"name": "📱 小米", "link": "http://xhww.fun:63/小米/DEMO.json"},
            {"name": "🚀 欧歌", "link": "http://tv.nxog.top/m"},
            {"name": "🐼 熊猫", "link": "https://jihulab.com/yw88075/tvbox/-/raw/main/tv/tv.json"},
        ]

    # 去重处理
    with get_db() as db:
        existens = {row['url'] for row in db.execute('SELECT url FROM sources WHERE user_id = ?', (session['user_id'],)).fetchall()}
    
    final_list, seen = [], set()
    for item in combined_list:
        link = item.get('link') or item.get('url')
        if link and link not in seen and link not in existens:
            final_list.append(item)
            seen.add(link)
    
    return jsonify_success(data=final_list[:40])

# --- Admin & Webhook APIs ---
@app.route('/api/admin/settings/code', methods=['POST'])
@admin_required
def api_admin_update_code():
    new_code = request.json.get('code', '').strip()
    if not new_code: return jsonify_error('不能为空')
    with get_db() as db:
        db.execute("UPDATE settings SET value = ? WHERE key = 'invite_code'", (new_code,))
        db.commit()
    return jsonify_success('已更新')

@app.route('/api/admin/settings/token', methods=['POST'])
@admin_required
def api_admin_update_token():
    new_token = secrets.token_hex(16)
    with get_db() as db:
        db.execute("UPDATE settings SET value = ? WHERE key = 'webhook_token'", (new_token,))
        db.commit()
    return jsonify_success('已重置', token=new_token)

@app.route('/api/admin/users')
@admin_required
def api_admin_users():
    with get_db() as db:
        users = db.execute('''
            SELECT u.id, u.username, u.created_at, COUNT(s.id) as source_count
            FROM users u LEFT JOIN sources s ON u.id = s.user_id
            GROUP BY u.id ORDER BY u.id DESC
        ''').fetchall()
    return jsonify_success(data=[dict(row) for row in users])

@app.route('/api/admin/users/delete', methods=['POST'])
@admin_required
def api_admin_users_delete():
    uid = request.json.get('id')
    with get_db() as db:
        db.execute('DELETE FROM sources WHERE user_id = ?', (uid,))
        db.execute('DELETE FROM users WHERE id = ?', (uid,))
        db.commit()
    return jsonify_success('已删除')

@app.route('/api/admin/recommendations/push', methods=['POST'])
def api_admin_push_recommendations():
    data = request.json
    pwd = data.get('password') or data.get('token') or request.headers.get('Authorization', '').replace('Bearer ', '')
    
    with get_db() as db:
        expected = db.execute("SELECT value FROM settings WHERE key = 'webhook_token'").fetchone()['value']
    if not expected or pwd != expected: return jsonify_error('未授权', 401)
        
    items = data.get('list', [])
    normalized = []
    for it in items:
        link = it if isinstance(it, str) else (it.get('link') or it.get('url'))
        name = "推荐源" if isinstance(it, str) else it.get('name', '推荐源')
        if link: normalized.append({"name": name, "link": link})
    
    try:
        save_path = '/app/data/recommended.json' if os.path.exists('/app/data') else 'data/recommended.json'
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump({'list': normalized}, f, ensure_ascii=False)
        return jsonify_success(f'成功更新 {len(normalized)} 条推荐源')
    except Exception as e: return jsonify_error(str(e))

# --- Public Subscription API ---
@app.route('/api/subscribe/<username>.json')
def get_tvbox_json(username):
    etype, only_online = request.args.get('type', 'multi'), request.args.get('only_online') == 'true'
    
    with get_db() as db:
        user = db.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
        if not user: return jsonify_error('用户不存在', 404)
            
        sql = 'SELECT * FROM sources WHERE user_id = ?' + (' AND status = "online"' if only_online else '') + ' ORDER BY order_index ASC, id ASC'
        sources = db.execute(sql, (user['id'],)).fetchall()
    
    if etype == 'single':
        config = { "sites": [], "lives": [{"name": "live", "type": 0, "url": "", "playerType": 1}] }
        lives = []
        for r in sources:
            if r['type'] == 'site':
                config["sites"].append({"key": f"s_{r['id']}", "name": r['name'], "type": 3, "api": "csp_XBPQ", "ext": r['url']})
            else: lives.append(f"{r['name']}, {r['url']}")
        if lives: config["lives"][0]["url"] = "#".join(lives)
    else:
        config = {"urls": [{"url": r['url'], "name": r['name']} for r in sources]}
            
    json_str = json.dumps(config, indent=4, ensure_ascii=False)
    if request.args.get('comment') == 'true':
        json_str = f"//TVBox 专属配置 - {'多仓' if etype == 'multi' else '单仓'}\n" + json_str
    
    res = Response(json_str, mimetype='application/json; charset=utf-8')
    res.headers.add('Access-Control-Allow-Origin', '*')
    return res

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8089)

import os
import sqlite3
from flask import Flask, request, session, redirect, url_for, render_template, jsonify, Response
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import json
import requests
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
# 适配反向代理，处理 X-Forwarded-Proto 等头部
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

# secret_key 从环境变量读取，容器升级重建后 session 不失效
app.secret_key = os.environ.get('SECRET_KEY', 'super-secret-starlink-clone-key')
DATABASE = os.environ.get('DB_PATH', '/app/data/database.db')
REG_CODE = os.environ.get('REG_CODE', '888888')
BASE_URL = os.environ.get('BASE_URL', '').rstrip('/')

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                type TEXT DEFAULT 'site',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        db.commit()

# Ensure DB is initialized before first request
init_db()

# --- Auth Decorator ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- Frontend Routes ---
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login')
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/register')
def register():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('register.html')

@app.route('/dashboard')
@login_required
def dashboard():
    username = session.get('username')
    # If BASE_URL is set, use it; otherwise fallback to request.host_url
    host_url = BASE_URL if BASE_URL else request.host_url.rstrip('/')
    sub_url = host_url + url_for('get_tvbox_json', username=username)
    return render_template('dashboard.html', username=username, sub_url=sub_url)

# --- API Routes ---
@app.route('/api/auth/register', methods=['POST'])
def api_register():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '')
    invite_code = data.get('invite_code', '').strip()

    if invite_code != REG_CODE:
        return jsonify({'status': 'error', 'message': '专属邀请码不正确，拒绝注册！'})

    if not username or not password:
        return jsonify({'status': 'error', 'message': '用户名和密码不能为空'})

    try:
        with get_db() as db:
            db.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', 
                       (username, generate_password_hash(password, method='pbkdf2:sha256')))
            db.commit()
            return jsonify({'status': 'success', 'message': '注册成功'})
    except sqlite3.IntegrityError:
        return jsonify({'status': 'error', 'message': '用户名已存在'})

@app.route('/api/auth/login', methods=['POST'])
def api_login():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '')

    with get_db() as db:
        user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        
    if user and check_password_hash(user['password_hash'], password):
        session['user_id'] = user['id']
        session['username'] = user['username']
        return jsonify({'status': 'success', 'message': '登录成功'})
    else:
        return jsonify({'status': 'error', 'message': '用户名或密码错误'})

@app.route('/api/auth/logout', methods=['GET'])
def api_logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/api/source/list', methods=['GET'])
@login_required
def api_source_list():
    user_id = session['user_id']
    with get_db() as db:
        sources = db.execute('SELECT * FROM sources WHERE user_id = ? ORDER BY id DESC', (user_id,)).fetchall()
        sources_list = [dict(row) for row in sources]
    return jsonify({'status': 'success', 'data': sources_list})

@app.route('/api/source/add', methods=['POST'])
@login_required
def api_source_add():
    user_id = session['user_id']
    data = request.json
    name = data.get('name', '').strip()
    url = data.get('url', '').strip()
    stype = data.get('type', 'site').strip() # 'site' or 'live'

    if not name or not url:
        return jsonify({'status': 'error', 'message': '名称和URL不能为空'})

    # 尝试自动解析多仓 JSON (Deconstruct Multi-Repo)
    try:
        # 只针对可能是 JSON 的 URL 进行尝试 (包含 urls 关键字或以 .json 结尾)
        if 'urls' in url or url.endswith('.json'):
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                json_data = r.json()
                if isinstance(json_data, dict) and "urls" in json_data and isinstance(json_data["urls"], list):
                    added_count = 0
                    with get_db() as db:
                        for entry in json_data["urls"]:
                            e_name = entry.get('name', '未命名').strip()
                            e_url = entry.get('url', '').strip()
                            if e_url:
                                db.execute('INSERT INTO sources (user_id, name, url, type) VALUES (?, ?, ?, ?)', 
                                           (user_id, e_name, e_url, stype))
                                added_count += 1
                        db.commit()
                    return jsonify({'status': 'success', 'message': f'检测到聚合接口，已分解并导入 {added_count} 个子接口！'})
    except Exception:
        # 解析失败或不是 JSON，退回到单个普通接口添加模式
        pass

    with get_db() as db:
        db.execute('INSERT INTO sources (user_id, name, url, type) VALUES (?, ?, ?, ?)', 
                   (user_id, name, url, stype))
        db.commit()
    return jsonify({'status': 'success', 'message': '添加成功'})

@app.route('/api/source/delete', methods=['POST'])
@login_required
def api_source_delete():
    user_id = session['user_id']
    source_id = request.json.get('id')
    with get_db() as db:
        db.execute('DELETE FROM sources WHERE id = ? AND user_id = ?', (source_id, user_id))
        db.commit()
    return jsonify({'status': 'success', 'message': '删除成功'})

@app.route('/api/source/update', methods=['POST'])
@login_required
def api_source_update():
    user_id = session['user_id']
    data = request.json
    source_id = data.get('id')
    name = data.get('name', '').strip()
    url = data.get('url', '').strip()
    stype = data.get('type', 'site').strip()
    
    if not source_id or not name or not url:
        return jsonify({'status': 'error', 'message': '名称和URL不能为空'})

    with get_db() as db:
        db.execute('UPDATE sources SET name = ?, url = ?, type = ? WHERE id = ? AND user_id = ?', 
                   (name, url, stype, source_id, user_id))
        db.commit()
    return jsonify({'status': 'success', 'message': '保存成功'})

@app.route('/api/source/check', methods=['POST'])
@login_required
def api_source_check():
    url = request.json.get('url')
    if not url:
        return jsonify({'status': 'error', 'message': 'URL missing'})
    try:
        # 只取头信息或者前几个字节，避免下载大文件
        r = requests.get(url, timeout=5, stream=True)
        r.close() # 立即关闭连接
        if r.status_code < 400:
            return jsonify({'status': 'success', 'code': r.status_code})
        else:
            return jsonify({'status': 'error', 'code': r.status_code})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

# --- The Core TVBOX JSON Generation API ---
@app.route('/api/subscribe/<username>.json')
def get_tvbox_json(username):
    """
    Generate TVBox standard JSON configuration based on the user's saved sources.
    Supports ?type=single or ?type=multi (default)
    """
    export_type = request.args.get('type', 'multi')
    
    with get_db() as db:
        user = db.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
        if not user:
            return jsonify({'error': '用户不存在'}), 404
            
        sources = db.execute('SELECT * FROM sources WHERE user_id = ?', (user['id'],)).fetchall()
    
    if export_type == 'single':
        # Single Repo Format ( sites, lives, etc)
        tvbox_config = {
            "sites": [],
            "lives": [{"name": "live", "type": 0, "url": "", "playerType": 1, "ua": "", "epg": "", "logo": ""}]
        }
        live_urls = []
        for row in sources:
            if row['type'] == 'site':
                tvbox_config["sites"].append({
                    "key": f"site_{row['id']}",
                    "name": row['name'],
                    "type": 3,
                    "api": "csp_XBPQ",
                    "searchable": 1,
                    "quickSearch": 1,
                    "filterable": 1,
                    "ext": row['url']
                })
            else:
                live_urls.append(f"{row['name']}, {row['url']}")
        
        if live_urls:
            tvbox_config["lives"][0]["url"] = "#".join(live_urls)
            
    else:
        # Multi-repo TVBox JSON Structure (多仓格式)
        tvbox_config = {
            "urls": []
        }
        for row in sources:
            tvbox_config["urls"].append({
                "url": row['url'],
                "name": row['name']
            })
            
    json_str = json.dumps(tvbox_config, indent=4, ensure_ascii=False)
    
    # Check if user explicitly wants the comment (older apps might need it for some reason)
    if request.args.get('comment') == 'true':
        final_output = "//影视仓专属配置源 - " + ("多仓模式" if export_type == 'multi' else "单仓模式") + "\n" + json_str
    else:
        final_output = json_str
    
    response = Response(final_output, mimetype='application/json; charset=utf-8')
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response

if __name__ == '__main__':
    # Run the Flask app on localhost:5000
    app.run(host='0.0.0.0', port=8089, debug=True)

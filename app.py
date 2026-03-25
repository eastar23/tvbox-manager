import os
import sqlite3
from flask import Flask, request, session, redirect, url_for, render_template, jsonify, Response
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import json

app = Flask(__name__)
app.secret_key = 'super-secret-starlink-clone-key'  # In production, use os.urandom(24)
DATABASE = os.environ.get('DB_PATH', 'database.db')
REG_CODE = os.environ.get('REG_CODE', '888888')

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
    sub_url = request.host_url.rstrip('/') + url_for('get_tvbox_json', username=username)
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

# --- The Core TVBOX JSON Generation API ---
@app.route('/api/subscribe/<username>.json')
def get_tvbox_json(username):
    """
    Generate TVBox standard JSON configuration based on the user's saved sources.
    This URL acts as the subscription link.
    """
    with get_db() as db:
        user = db.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
        if not user:
            return jsonify({'error': '用户不存在'}), 404
            
        sources = db.execute('SELECT * FROM sources WHERE user_id = ?', (user['id'],)).fetchall()
    
    # Construct Multi-repo TVBox JSON Structure (多仓格式)
    tvbox_config = {
        "urls": []
    }
    
    for row in sources:
        tvbox_config["urls"].append({
            "url": row['url'],
            "name": row['name']
        })
            
    # Return as JSON with ensuring no unicode escapes (ensure_ascii=False)
    json_str = json.dumps(tvbox_config, indent=4, ensure_ascii=False)
    
    # Optional header comment to match starlink.uno format
    final_output = "//影视仓专属多仓配置源\n" + json_str
    
    response = Response(final_output, mimetype='application/json; charset=utf-8')
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response

if __name__ == '__main__':
    # Run the Flask app on localhost:5000
    app.run(host='0.0.0.0', port=8089, debug=True)

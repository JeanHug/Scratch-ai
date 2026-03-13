import os
import time
import json
import requests as http_requests
from flask import Flask, request, jsonify, render_template_string
import scratchattach as scratch

app = Flask(__name__)

CHARS = " abcdefghijklmnopqrstuvwxyz0123456789.,!?@'\"()+-*/=:_éàè"
PROJECT_ID = os.getenv("SCRATCH_ID", "")
SCRATCH_USER = os.getenv("SCRATCH_USER", "")
SCRATCH_PASS = os.getenv("SCRATCH_PASS", "")

logs = []
session_obj = None
conn = None

def log(msg):
    t = time.strftime("%H:%M:%S")
    entry = f"[{t}] {msg}"
    logs.append(entry)
    if len(logs) > 100:
        logs.pop(0)
    print(entry, flush=True)

def encode(text):
    r = "2"
    for c in text.lower():
        if c in CHARS:
            r += str(CHARS.index(c) + 1).zfill(2)
    return r

def decode(s):
    s = str(s)[1:]
    t = ""
    for i in range(0, len(s), 2):
        idx = int(s[i:i+2])
        if 1 <= idx <= len(CHARS):
            t += CHARS[idx - 1]
    return t

# ══════════════════════════════════════
# PAGE PRINCIPALE
# ══════════════════════════════════════

HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Test Scratch Cloud</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: monospace; background: #fff; padding: 20px; }
h1 { font-size: 20px; margin-bottom: 10px; border-bottom: 2px solid #000; padding-bottom: 5px; }
h2 { font-size: 14px; margin: 10px 0 5px 0; }
.row { display: flex; gap: 20px; flex-wrap: wrap; }
.col { flex: 1; min-width: 300px; }
.box { border: 1px solid #000; padding: 10px; margin-bottom: 10px; }
button { padding: 6px 14px; border: 1px solid #000; background: #fff; cursor: pointer;
         font-family: monospace; font-size: 13px; margin: 2px; }
button:hover { background: #ddd; }
input { padding: 6px; border: 1px solid #000; font-family: monospace; width: 100%;
        margin-bottom: 5px; font-size: 13px; }
#logs { background: #f5f5f5; border: 1px solid #000; padding: 8px; height: 250px;
        overflow-y: auto; font-size: 11px; line-height: 1.5; }
.ok { color: green; font-weight: bold; }
.err { color: red; font-weight: bold; }
.info { color: #333; }
iframe { border: 1px solid #000; width: 100%; }
.status_bar { padding: 6px; border: 1px solid #000; margin-bottom: 10px;
              font-size: 13px; background: #ffe; }
</style>
</head>
<body>

<h1>🔧 Scratch Cloud — Diagnostic</h1>
<div class="status_bar" id="status">En attente...</div>

<div class="row">
<div class="col">

    <div class="box">
        <h2>1. CONNEXION SCRATCH</h2>
        <button onclick="api('/connect')">Se connecter</button>
        <button onclick="api('/check_session')">Vérifier session</button>
        <button onclick="api('/version')">Version scratchattach</button>
    </div>

    <div class="box">
        <h2>2. LIRE VARIABLE CLOUD</h2>
        <button onclick="api('/read_via_conn')">Lire via conn</button>
        <button onclick="api('/read_via_api')">Lire via API REST</button>
        <button onclick="api('/read_via_logs')">Lire via cloud logs</button>
    </div>

    <div class="box">
        <h2>3. ÉCRIRE VARIABLE CLOUD</h2>
        <input type="text" id="msg" placeholder="Message texte (ex: salut)">
        <button onclick="api('/write_encoded?msg='+encodeURIComponent(document.getElementById('msg').value))">
            Envoyer encodé (préfixe 2)</button>
        <input type="text" id="raw" placeholder="Valeur brute (ex: 12345)">
        <button onclick="api('/write_raw?val='+encodeURIComponent(document.getElementById('raw').value))">
            Envoyer brut</button>
        <button onclick="api('/write_raw?val=0')">Remettre à 0</button>
    </div>

    <div class="box">
        <h2>📋 LOGS</h2>
        <button onclick="refreshLogs()">Rafraîchir</button>
        <button onclick="api('/clear')">Effacer</button>
        <div id="logs"></div>
    </div>

</div>
<div class="col">

    <div class="box">
        <h2>🎮 PROJET SCRATCH</h2>
        <iframe src="https://scratch.mit.edu/projects/PROJ_ID/embed"
                height="400" allowfullscreen></iframe>
    </div>

    <div class="box">
        <h2>📊 CLOUD DATA (chargé par le serveur)</h2>
        <button onclick="reloadCloud()">🔄 Recharger les données cloud</button>
        <iframe id="cloud_frame" src="/cloud_viewer" height="300"></iframe>
    </div>

    <div class="box">
        <h2>📊 VALEUR ACTUELLE</h2>
        <button onclick="reloadCurrent()">🔄 Recharger</button>
        <iframe id="current_frame" src="/current_value" height="100"></iframe>
    </div>

    <div class="box">
        <h2>ℹ️ INFOS</h2>
        <div style="font-size:12px; line-height:1.6;">
            Projet : <b>PROJ_ID</b><br>
            User : <b>SCRATCH_U</b><br>
            Pass : <b>PASS_MASK</b>
        </div>
    </div>

</div>
</div>

<script>
function api(url) {
    document.getElementById('status').innerText = 'Requête : ' + url + '...';
    fetch(url)
        .then(r => r.json())
        .then(d => {
            document.getElementById('status').innerText = d.status || JSON.stringify(d);
            refreshLogs();
            reloadCurrent();
        })
        .catch(e => {
            document.getElementById('status').innerText = 'FETCH ÉCHOUÉ : ' + e;
        });
}
function refreshLogs() {
    fetch('/logs').then(r => r.json()).then(d => {
        let html = '';
        d.logs.forEach(l => {
            let cls = 'info';
            if (l.includes('✅') || l.includes('OK')) cls = 'ok';
            if (l.includes('❌') || l.includes('ERREUR') || l.includes('choué')) cls = 'err';
            html += '<div class="' + cls + '">' + l + '</div>';
        });
        document.getElementById('logs').innerHTML = html;
        let el = document.getElementById('logs');
        el.scrollTop = el.scrollHeight;
    });
}
function reloadCloud() {
    document.getElementById('cloud_frame').src = '/cloud_viewer?' + Date.now();
}
function reloadCurrent() {
    document.getElementById('current_frame').src = '/current_value?' + Date.now();
}
setInterval(refreshLogs, 3000);
setInterval(reloadCurrent, 5000);
refreshLogs();
</script>
</body>
</html>
""".replace("PROJ_ID", PROJECT_ID).replace("SCRATCH_U", SCRATCH_USER).replace("PASS_MASK", "*" * len(SCRATCH_PASS) if SCRATCH_PASS else "VIDE ❌")


# ══════════════════════════════════════
# PAGES IFRAME (chargées par le serveur)
# ══════════════════════════════════════

@app.route('/cloud_viewer')
def cloud_viewer():
    """Charge les cloud logs côté serveur et les affiche en HTML"""
    try:
        url = f"https://clouddata.scratch.mit.edu/logs?projectid={PROJECT_ID}&limit=30&offset=0"
        r = http_requests.get(url, timeout=10)

        if r.status_code != 200:
            return f"<pre style='font-family:monospace;color:red'>Erreur HTTP {r.status_code}\n{r.text}</pre>"

        lines = r.text.strip().split('\n')
        html = """<html><head><meta charset="utf-8">
        <style>
        body { font-family: monospace; font-size: 12px; margin: 5px; background: #f9f9f9; }
        table { border-collapse: collapse; width: 100%; }
        td, th { border: 1px solid #ccc; padding: 3px 6px; text-align: left; }
        th { background: #eee; }
        .val { font-weight: bold; color: #333; }
        .decoded { color: blue; }
        </style></head><body>
        <table><tr><th>Variable</th><th>Valeur brute</th><th>Décodé</th><th>Par</th><th>Quand</th></tr>"""

        for line in lines:
            try:
                d = json.loads(line)
                name = d.get('name', '?').replace('☁ ', '')
                val = str(d.get('value', '?'))
                user = d.get('user', '?')
                ts = d.get('timestamp', 0)
                t = time.strftime('%H:%M:%S', time.localtime(ts / 1000)) if ts else '?'

                decoded = ""
                val_clean = val.split('.')[0]
                if val_clean.startswith('1') and len(val_clean) > 2:
                    try:
                        decoded = decode(val_clean)
                    except:
                        decoded = "?"
                elif val_clean.startswith('2') and len(val_clean) > 2:
                    try:
                        decoded = decode(val_clean)
                    except:
                        decoded = "?"

                html += f'<tr><td>{name}</td><td class="val">{val}</td>'
                html += f'<td class="decoded">{decoded}</td><td>{user}</td><td>{t}</td></tr>'
            except:
                html += f'<tr><td colspan="5">{line[:100]}</td></tr>'

        html += "</table></body></html>"
        return html

    except Exception as e:
        return f"<pre style='font-family:monospace;color:red'>Erreur : {e}</pre>"


@app.route('/current_value')
def current_value():
    """Affiche la valeur actuelle de la variable"""
    try:
        url = f"https://clouddata.scratch.mit.edu/logs?projectid={PROJECT_ID}&limit=5&offset=0"
        r = http_requests.get(url, timeout=10)
        lines = r.text.strip().split('\n')

        for line in lines:
            try:
                d = json.loads(line)
                if 'Messages sent' in d.get('name', ''):
                    val = str(d.get('value', '0')).split('.')[0]
                    decoded = ""
                    if (val.startswith('1') or val.startswith('2')) and len(val) > 2:
                        try:
                            decoded = decode(val)
                        except:
                            decoded = "?"

                    prefix = "USER→" if val.startswith('1') else "BOT→" if val.startswith('2') else ""
                    color = "blue" if val.startswith('1') else "green" if val.startswith('2') else "black"

                    return f"""<html><body style="font-family:monospace;font-size:13px;margin:5px">
                    <b>☁ Messages sent</b> = <span style="color:{color}">{val}</span><br>
                    <b>{prefix}</b> <span style="color:{color};font-size:16px">{decoded}</span>
                    </body></html>"""
            except:
                pass

        return "<html><body style='font-family:monospace;margin:5px'>Aucune donnée trouvée</body></html>"

    except Exception as e:
        return f"<html><body style='font-family:monospace;color:red;margin:5px'>Erreur : {e}</body></html>"


# ══════════════════════════════════════
# ROUTES API
# ══════════════════════════════════════

@app.route('/')
def home():
    return render_template_string(HTML)

@app.route('/version')
def version():
    try:
        v = scratch.__version__ if hasattr(scratch, '__version__') else "inconnue"
        log(f"📦 scratchattach version : {v}")
        if conn:
            methods = [m for m in dir(conn) if not m.startswith('_') and callable(getattr(conn, m, None))]
            log(f"📦 Méthodes conn : {methods}")
        return jsonify(status=f"Version : {v}")
    except Exception as e:
        log(f"❌ {e}")
        return jsonify(status=str(e))

@app.route('/connect')
def connect():
    global session_obj, conn
    try:
        log(f"🔌 Login avec user={SCRATCH_USER}...")
        session_obj = scratch.login(SCRATCH_USER, SCRATCH_PASS)
        log("✅ Login OK")
    except Exception as e:
        log(f"❌ Login échoué : {e}")
        return jsonify(status=f"Login échoué : {e}")
    try:
        log(f"🔌 Connexion cloud projet {PROJECT_ID}...")
        conn = session_obj.connect_cloud(PROJECT_ID)
        log("✅ Cloud connecté")
        methods = [m for m in dir(conn) if not m.startswith('_') and callable(getattr(conn, m, None))]
        log(f"📦 Méthodes : {methods}")
        return jsonify(status="Connecté ✅")
    except Exception as e:
        log(f"❌ Cloud échoué : {e}")
        return jsonify(status=f"Cloud échoué : {e}")

@app.route('/check_session')
def check_session():
    log(f"session_obj = {session_obj}")
    log(f"conn = {conn}")
    return jsonify(status=f"session={session_obj is not None}, conn={conn is not None}")

@app.route('/read_via_conn')
def read_via_conn():
    if not conn:
        log("❌ Pas connecté")
        return jsonify(status="Pas connecté")
    for name in ["Messages sent", "☁ Messages sent"]:
        try:
            val = conn.get_var(name)
            log(f"📖 conn.get_var('{name}') → {val} (type: {type(val).__name__})")
            return jsonify(status=f"Lu : {val}")
        except Exception as e:
            log(f"❌ get_var('{name}') : {e}")
    return jsonify(status="Toutes les lectures ont échoué")

@app.route('/read_via_api')
def read_via_api():
    try:
        url = f"https://clouddata.scratch.mit.edu/logs?projectid={PROJECT_ID}&limit=5&offset=0"
        log(f"📡 GET {url}")
        r = http_requests.get(url, timeout=10)
        log(f"📡 HTTP {r.status_code}")
        lines = r.text.strip().split('\n')
        for line in lines:
            try:
                data = json.loads(line)
                if 'Messages sent' in data.get('name', ''):
                    val = data['value']
                    log(f"📖 API → {data['name']} = {val}")
                    return jsonify(status=f"API : {val}")
            except:
                pass
        log(f"📡 {len(lines)} lignes, pas de Messages sent trouvé")
        log(f"📡 Premières données : {r.text[:300]}")
        return jsonify(status=f"{len(lines)} lignes reçues")
    except Exception as e:
        log(f"❌ API échoué : {e}")
        return jsonify(status=f"Erreur : {e}")

@app.route('/read_via_logs')
def read_via_logs():
    try:
        cloud = scratch.get_cloud(PROJECT_ID)
        log(f"📦 Type : {type(cloud).__name__}")
        for name in ["Messages sent", "☁ Messages sent"]:
            try:
                val = cloud.get_var(name)
                log(f"📖 get_cloud().get_var('{name}') → {val}")
                return jsonify(status=f"Lu : {val}")
            except Exception as e:
                log(f"❌ get_var('{name}') : {e}")
        return jsonify(status="Échoué")
    except Exception as e:
        log(f"❌ get_cloud échoué : {e}")
        return jsonify(status=f"Erreur : {e}")

@app.route('/write_encoded')
def write_encoded():
    msg = request.args.get('msg', '')
    if not conn:
        log("❌ Pas connecté")
        return jsonify(status="Pas connecté — clique Se connecter d'abord")
    try:
        encoded = encode(msg)
        log(f"📤 Texte : '{msg}' → Encodé : {encoded}")
        for name in ["Messages sent", "☁ Messages sent"]:
            try:
                conn.set_var(name, encoded)
                log(f"✅ set_var('{name}', {encoded})")
                return jsonify(status=f"Envoyé via '{name}'")
            except Exception as e:
                log(f"❌ set_var('{name}') : {e}")
        return jsonify(status="Toutes les écritures ont échoué")
    except Exception as e:
        log(f"❌ {e}")
        return jsonify(status=f"Erreur : {e}")

@app.route('/write_raw')
def write_raw():
    val = request.args.get('val', '0')
    if not conn:
        log("❌ Pas connecté")
        return jsonify(status="Pas connecté")
    for name in ["Messages sent", "☁ Messages sent"]:
        try:
            conn.set_var(name, val)
            log(f"✅ set_var('{name}', {val})")
            return jsonify(status=f"Écrit '{name}' = {val}")
        except Exception as e:
            log(f"❌ set_var('{name}') : {e}")
    return jsonify(status="Échec")

@app.route('/logs')
def get_logs():
    return jsonify(logs=logs)

@app.route('/clear')
def clear():
    logs.clear()
    return jsonify(status="Logs effacés")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

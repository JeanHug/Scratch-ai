import os
import time
import json
import requests
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
#cloud_raw { background: #f5f5f5; border: 1px solid #000; padding: 8px; height: 150px;
             overflow-y: auto; font-size: 11px; white-space: pre-wrap; }
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
        <h2>4. CLOUD DATA (API Scratch directe)</h2>
        <button onclick="loadCloud()">Charger les logs cloud</button>
        <div id="cloud_raw">Clique sur le bouton...</div>
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
        <h2>🎮 PROJET SCRATCH (embed)</h2>
        <iframe src="https://scratch.mit.edu/projects/""" + PROJECT_ID + """/embed"
                height="400" allowfullscreen></iframe>
    </div>

    <div class="box">
        <h2>📊 CLOUD DATA VIEWER</h2>
        <iframe id="cloud_iframe"
                src="https://clouddata.scratch.mit.edu/logs?projectid=""" + PROJECT_ID + """&limit=20&offset=0"
                height="300"></iframe>
        <button onclick="document.getElementById('cloud_iframe').src=document.getElementById('cloud_iframe').src">
            Recharger</button>
    </div>

    <div class="box">
        <h2>ℹ️ INFOS</h2>
        <div style="font-size:12px; line-height:1.6;">
            Projet : <b>""" + PROJECT_ID + """</b><br>
            User : <b>""" + SCRATCH_USER + """</b><br>
            Pass : <b>""" + ("*" * len(SCRATCH_PASS) if SCRATCH_PASS else "VIDE ❌") + """</b>
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

function loadCloud() {
    document.getElementById('cloud_raw').innerText = 'Chargement...';
    fetch('https://clouddata.scratch.mit.edu/logs?projectid=""" + PROJECT_ID + """&limit=20&offset=0')
        .then(r => r.text())
        .then(t => {
            document.getElementById('cloud_raw').innerText = t || '(vide)';
        })
        .catch(e => {
            document.getElementById('cloud_raw').innerText = 'Erreur : ' + e;
        });
}

setInterval(refreshLogs, 3000);
refreshLogs();
</script>
</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(HTML)

@app.route('/version')
def version():
    try:
        v = scratch.__version__ if hasattr(scratch, '__version__') else "inconnue"
        log(f"📦 scratchattach version : {v}")
        # Lister les méthodes disponibles
        if conn:
            methods = [m for m in dir(conn) if not m.startswith('_')]
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
        log(f"✅ Login OK")
        log(f"📦 Type session : {type(session_obj)}")
    except Exception as e:
        log(f"❌ Login échoué : {e}")
        return jsonify(status=f"Login échoué : {e}")

    try:
        log(f"🔌 Connexion cloud projet {PROJECT_ID}...")
        conn = session_obj.connect_cloud(PROJECT_ID)
        log(f"✅ Cloud connecté")
        log(f"📦 Type conn : {type(conn)}")
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
    log(f"type conn = {type(conn) if conn else 'None'}")
    return jsonify(status=f"session={session_obj is not None}, conn={conn is not None}")

@app.route('/read_via_conn')
def read_via_conn():
    if not conn:
        log("❌ Pas connecté")
        return jsonify(status="Pas connecté")
    try:
        val = conn.get_var("Messages sent")
        log(f"📖 conn.get_var → {val} (type: {type(val)})")
        return jsonify(status=f"Lu : {val}")
    except Exception as e:
        log(f"❌ conn.get_var échoué : {e}")

    # Essai avec le préfixe ☁
    try:
        val = conn.get_var("☁ Messages sent")
        log(f"📖 conn.get_var(☁) → {val}")
        return jsonify(status=f"Lu (☁) : {val}")
    except Exception as e2:
        log(f"❌ conn.get_var(☁) échoué : {e2}")
        return jsonify(status=f"Échoué : {e} / {e2}")

@app.route('/read_via_api')
def read_via_api():
    try:
        url = f"https://clouddata.scratch.mit.edu/logs?projectid={PROJECT_ID}&limit=5&offset=0"
        log(f"📡 GET {url}")
        r = requests.get(url, timeout=10)
        log(f"📡 Status HTTP : {r.status_code}")
        log(f"📡 Réponse : {r.text[:500]}")

        # Parser pour trouver Messages sent
        lines = r.text.strip().split('\n')
        for line in lines:
            try:
                data = json.loads(line)
                if 'Messages sent' in data.get('name', ''):
                    log(f"📖 API → {data['name']} = {data['value']}")
                    return jsonify(status=f"API : {data['value']}")
            except:
                pass
        return jsonify(status=f"Données reçues, {len(lines)} lignes")
    except Exception as e:
        log(f"❌ API échoué : {e}")
        return jsonify(status=f"Erreur : {e}")

@app.route('/read_via_logs')
def read_via_logs():
    try:
        cloud = scratch.get_cloud(PROJECT_ID)
        log(f"📦 Type cloud : {type(cloud)}")
        methods = [m for m in dir(cloud) if not m.startswith('_')]
        log(f"📦 Méthodes : {methods}")

        # Essayer plusieurs façons de lire
        for name in ["Messages sent", "☁ Messages sent"]:
            try:
                val = cloud.get_var(name)
                log(f"📖 get_cloud().get_var('{name}') → {val}")
                return jsonify(status=f"Lu : {val}")
            except Exception as e:
                log(f"❌ get_var('{name}') : {e}")

        return jsonify(status="Toutes les méthodes de lecture ont échoué")
    except Exception as e:
        log(f"❌ get_cloud échoué : {e}")
        return jsonify(status=f"Erreur : {e}")

@app.route('/write_encoded')
def write_encoded():
    msg = request.args.get('msg', '')
    if not conn:
        log("❌ Pas connecté")
        return jsonify(status="Pas connecté")
    try:
        encoded = encode(msg)
        log(f"📤 Texte : '{msg}'")
        log(f"📤 Encodé : {encoded}")

        # Essayer les deux noms
        for name in ["Messages sent", "☁ Messages sent"]:
            try:
                conn.set_var(name, encoded)
                log(f"✅ set_var('{name}', {encoded}) → OK")
                return jsonify(status=f"Envoyé via '{name}' : {encoded}")
            except Exception as e:
                log(f"❌ set_var('{name}') échoué : {e}")

        return jsonify(status="Toutes les écritures ont échoué")
    except Exception as e:
        log(f"❌ Encodage échoué : {e}")
        return jsonify(status=f"Erreur : {e}")

@app.route('/write_raw')
def write_raw():
    val = request.args.get('val', '0')
    if not conn:
        log("❌ Pas connecté")
        return jsonify(status="Pas connecté")
    try:
        for name in ["Messages sent", "☁ Messages sent"]:
            try:
                conn.set_var(name, val)
                log(f"✅ set_var('{name}', {val}) → OK")
                return jsonify(status=f"Écrit '{name}' = {val}")
            except Exception as e:
                log(f"❌ set_var('{name}') échoué : {e}")
        return jsonify(status="Échec")
    except Exception as e:
        log(f"❌ {e}")
        return jsonify(status=f"Erreur : {e}")

@app.route('/logs')
def get_logs():
    return jsonify(logs=logs)

@app.route('/clear')
def clear():
    logs.clear()
    return jsonify(status="Logs effacés")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

import os
import time
from flask import Flask, request, jsonify, render_template_string
import scratchattach as scratch
import google.generativeai as genai

app = Flask(__name__)

# ── Config ──
CHARS = " abcdefghijklmnopqrstuvwxyz0123456789.,!?@'\"()+-*/=:_éàè"
PROJECT_ID = os.getenv("SCRATCH_ID")
logs = []
conn = None

def log(msg):
    t = time.strftime("%H:%M:%S")
    entry = f"[{t}] {msg}"
    logs.append(entry)
    if len(logs) > 50:
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

def get_connection():
    global conn
    if conn is not None:
        return conn
    try:
        log("🔌 Connexion à Scratch...")
        s = scratch.login(os.getenv("SCRATCH_USER"), os.getenv("SCRATCH_PASS"))
        conn = s.connect_cloud(PROJECT_ID)
        log("✅ Connecté à Scratch !")
        return conn
    except Exception as e:
        log(f"❌ Connexion échouée : {e}")
        conn = None
        return None

# ── Page HTML ──
HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Test Scratch Cloud</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: monospace; background: white; padding: 20px; max-width: 700px; margin: auto; }
h1 { font-size: 18px; margin-bottom: 15px; }
.section { border: 1px solid #ccc; padding: 15px; margin-bottom: 15px; }
.section h2 { font-size: 14px; margin-bottom: 10px; }
input[type=text] { width: 100%; padding: 8px; border: 1px solid #ccc; font-family: monospace; font-size: 14px; margin-bottom: 8px; }
button { padding: 8px 16px; border: 1px solid #333; background: white; cursor: pointer; font-family: monospace; font-size: 13px; margin-right: 5px; margin-bottom: 5px; }
button:hover { background: #eee; }
#logs { background: #f9f9f9; border: 1px solid #ccc; padding: 10px; height: 300px; overflow-y: auto; font-size: 12px; line-height: 1.6; }
.ok { color: green; }
.err { color: red; }
.info { color: #333; }
#status { padding: 8px; margin-bottom: 15px; border: 1px solid #ccc; font-size: 13px; }
</style>
</head>
<body>

<h1>🔧 Test Scratch Cloud</h1>

<div id="status">État : en attente</div>

<div class="section">
    <h2>1. Connexion</h2>
    <button onclick="action('/connect')">Se connecter à Scratch</button>
</div>

<div class="section">
    <h2>2. Lire la variable</h2>
    <button onclick="action('/read')">Lire ☁ Messages sent</button>
</div>

<div class="section">
    <h2>3. Écrire un message</h2>
    <input type="text" id="msg" placeholder="Tape un message ici...">
    <button onclick="sendMsg()">Envoyer (encodé avec préfixe 2)</button>
    <button onclick="sendRaw()">Envoyer brut (juste le chiffre)</button>
</div>

<div class="section">
    <h2>4. Remettre à zéro</h2>
    <button onclick="action('/reset')">Mettre ☁ Messages sent à 0</button>
</div>

<div class="section">
    <h2>5. Test IA</h2>
    <input type="text" id="ia_msg" placeholder="Question pour l'IA...">
    <button onclick="testIA()">Tester Gemini</button>
</div>

<div class="section">
    <h2>📋 Logs</h2>
    <button onclick="refreshLogs()">Rafraîchir</button>
    <button onclick="action('/clear')">Effacer</button>
    <div id="logs"></div>
</div>

<script>
function action(url) {
    fetch(url).then(r => r.json()).then(d => {
        document.getElementById('status').innerText = 'État : ' + d.status;
        refreshLogs();
    }).catch(e => {
        document.getElementById('status').innerText = 'ERREUR FETCH : ' + e;
    });
}

function sendMsg() {
    let msg = document.getElementById('msg').value;
    fetch('/send?msg=' + encodeURIComponent(msg))
        .then(r => r.json()).then(d => {
            document.getElementById('status').innerText = 'État : ' + d.status;
            refreshLogs();
        }).catch(e => {
            document.getElementById('status').innerText = 'ERREUR FETCH : ' + e;
        });
}

function sendRaw() {
    let msg = document.getElementById('msg').value;
    fetch('/send_raw?val=' + encodeURIComponent(msg))
        .then(r => r.json()).then(d => {
            document.getElementById('status').innerText = 'État : ' + d.status;
            refreshLogs();
        }).catch(e => {
            document.getElementById('status').innerText = 'ERREUR FETCH : ' + e;
        });
}

function testIA() {
    let msg = document.getElementById('ia_msg').value;
    document.getElementById('status').innerText = 'État : IA réfléchit...';
    fetch('/test_ia?q=' + encodeURIComponent(msg))
        .then(r => r.json()).then(d => {
            document.getElementById('status').innerText = 'État : ' + d.status;
            refreshLogs();
        }).catch(e => {
            document.getElementById('status').innerText = 'ERREUR FETCH : ' + e;
        });
}

function refreshLogs() {
    fetch('/logs').then(r => r.json()).then(d => {
        let html = '';
        d.logs.forEach(l => {
            let cls = 'info';
            if (l.includes('✅') || l.includes('OK')) cls = 'ok';
            if (l.includes('❌') || l.includes('ERREUR') || l.includes('échoué')) cls = 'err';
            html += '<div class="' + cls + '">' + l + '</div>';
        });
        document.getElementById('logs').innerHTML = html;
        let el = document.getElementById('logs');
        el.scrollTop = el.scrollHeight;
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

@app.route('/connect')
def connect():
    c = get_connection()
    if c:
        return jsonify(status="Connecté ✅")
    return jsonify(status="Connexion échouée ❌")

@app.route('/read')
def read():
    try:
        c = get_connection()
        if not c:
            return jsonify(status="Pas connecté ❌")
        val = c.get_var("Messages sent")
        val_str = str(val).split(".")[0]
        log(f"📖 Variable lue : {val_str}")
        if val_str.startswith("1"):
            decoded = decode(val_str)
            log(f"📖 Décodé (préfixe 1) : {decoded}")
        elif val_str.startswith("2"):
            decoded = decode(val_str)
            log(f"📖 Décodé (préfixe 2) : {decoded}")
        return jsonify(status=f"Valeur : {val_str}")
    except Exception as e:
        log(f"❌ Lecture échouée : {e}")
        return jsonify(status=f"Erreur lecture : {e}")

@app.route('/send')
def send():
    try:
        msg = request.args.get('msg', '')
        c = get_connection()
        if not c:
            return jsonify(status="Pas connecté ❌")
        encoded = encode(msg)
        log(f"📤 Message : '{msg}'")
        log(f"📤 Encodé : {encoded}")
        c.set_var("Messages sent", encoded)
        log(f"✅ Envoyé à Scratch !")
        return jsonify(status=f"Envoyé : {msg} → {encoded}")
    except Exception as e:
        log(f"❌ Envoi échoué : {e}")
        return jsonify(status=f"Erreur envoi : {e}")

@app.route('/send_raw')
def send_raw():
    try:
        val = request.args.get('val', '0')
        c = get_connection()
        if not c:
            return jsonify(status="Pas connecté ❌")
        c.set_var("Messages sent", val)
        log(f"📤 Envoyé brut : {val}")
        return jsonify(status=f"Envoyé brut : {val}")
    except Exception as e:
        log(f"❌ Envoi brut échoué : {e}")
        return jsonify(status=f"Erreur : {e}")

@app.route('/reset')
def reset():
    try:
        c = get_connection()
        if not c:
            return jsonify(status="Pas connecté ❌")
        c.set_var("Messages sent", "0")
        log("🔄 Variable remise à 0")
        return jsonify(status="Remis à 0 ✅")
    except Exception as e:
        log(f"❌ Reset échoué : {e}")
        return jsonify(status=f"Erreur : {e}")

@app.route('/test_ia')
def test_ia():
    try:
        q = request.args.get('q', 'dis bonjour')
        genai.configure(api_key=os.getenv("GEMINI_KEY"))
        m = genai.GenerativeModel('gemini-3-flash-preview')
        r = m.generate_content(q)
        txt = r.text.strip()[:100]
        log(f"🤖 Question : {q}")
        log(f"🤖 Réponse IA : {txt}")
        return jsonify(status=f"IA : {txt}")
    except Exception as e:
        log(f"❌ IA échouée : {e}")
        return jsonify(status=f"Erreur IA : {e}")

@app.route('/logs')
def get_logs():
    return jsonify(logs=logs)

@app.route('/clear')
def clear():
    logs.clear()
    return jsonify(status="Logs effacés")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

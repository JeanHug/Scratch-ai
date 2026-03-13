import os
import time
import json
import threading
import requests as http_requests
from flask import Flask, jsonify, render_template_string
import scratchattach as scratch
import google.generativeai as genai

app = Flask(__name__)

CHARS = " abcdefghijklmnopqrstuvwxyz0123456789.,!?@'\"()+-*/=:_éàè"
PROJECT_ID = os.getenv("SCRATCH_ID", "")
SCRATCH_USER = os.getenv("SCRATCH_USER", "")
SCRATCH_PASS = os.getenv("SCRATCH_PASS", "")
RENDER_URL = os.getenv("RENDER_URL", "")  # ex: https://ton-app.onrender.com

genai.configure(api_key=os.getenv("GEMINI_KEY"))
model = genai.GenerativeModel('gemini-3-flash-preview')

logs = []
conn = None
status = "Démarrage..."

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

def lire_variable():
    try:
        url = f"https://clouddata.scratch.mit.edu/logs?projectid={PROJECT_ID}&limit=5&offset=0"
        r = http_requests.get(url, timeout=10)
        for line in r.text.strip().split('\n'):
            try:
                d = json.loads(line)
                if 'Messages sent' in d.get('name', ''):
                    return str(d.get('value', '0')).split('.')[0]
            except:
                pass
    except:
        pass
    return "0"

def do_connect():
    global conn
    try:
        log("🔌 Connexion Scratch...")
        s = scratch.login(SCRATCH_USER, SCRATCH_PASS)
        conn = s.connect_cloud(PROJECT_ID)
        log("✅ Connecté !")
        return True
    except Exception as e:
        log(f"❌ Connexion : {e}")
        conn = None
        return False

# ══════════════════════════════
# BOUCLE IA (tourne toute seule)
# ══════════════════════════════

def boucle_ia():
    global status
    time.sleep(2)

    # Connexion automatique avec retry
    for tentative in range(5):
        if do_connect():
            break
        log(f"🔄 Nouvelle tentative dans 10s... ({tentative+1}/5)")
        time.sleep(10)

    if not conn:
        status = "❌ Connexion impossible"
        log("❌ Abandon après 5 tentatives")
        return

    status = "✅ En ligne"
    last = ""
    log("🔄 Boucle IA démarrée — tout est automatique !")

    while True:
        try:
            val = lire_variable()

            if val.startswith("1") and len(val) > 2 and val != last:
                last = val
                question = decode(val)
                status = f"🤖 Répond à : {question}"
                log(f"📩 Question : {question}")

                res = model.generate_content(
                    "Réponds en français, très court, max 30 caractères, "
                    "pas d'émoji, pas de markdown, pas de majuscules : " + question
                )
                reponse = ''.join(
                    c for c in res.text.strip().lower() if c in CHARS
                )[:40]
                log(f"🤖 Réponse : {reponse}")

                encoded = encode(reponse)
                conn.set_var("Messages sent", encoded)
                log(f"📤 Envoyé à Scratch !")
                status = "✅ En ligne"

            time.sleep(2)

        except Exception as e:
            log(f"❌ Erreur : {e}")
            status = "🔄 Reconnexion..."
            time.sleep(5)
            do_connect()
            if conn:
                status = "✅ En ligne"

# ══════════════════════════════
# SELF-PING (empêche Render de couper)
# ══════════════════════════════

def self_ping():
    time.sleep(30)
    while True:
        try:
            if RENDER_URL:
                http_requests.get(RENDER_URL, timeout=10)
                log("🏓 Self-ping OK")
            else:
                log("⚠️ RENDER_URL non défini — pas de self-ping")
        except:
            pass
        time.sleep(300)  # toutes les 5 minutes

# ══════════════════════════════
# PAGE WEB (juste pour vérifier)
# ══════════════════════════════

HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>IA Scratch</title>
<style>
body { font-family: monospace; background: #fff; padding: 20px;
       max-width: 500px; margin: auto; }
h1 { font-size: 18px; margin-bottom: 15px; }
#status { font-size: 16px; padding: 10px; border: 2px solid #000;
          margin-bottom: 10px; text-align: center; }
#logs { border: 1px solid #ccc; padding: 8px; height: 400px;
        overflow-y: auto; font-size: 11px; background: #f9f9f9;
        line-height: 1.6; }
.ok { color: green; font-weight: bold; }
.err { color: red; font-weight: bold; }
p { font-size: 11px; color: #888; margin: 8px 0; }
</style>
</head>
<body>
<h1>🤖 IA Scratch</h1>
<div id="status">...</div>
<p>Tout est automatique. Tu n'as pas besoin de garder cette page ouverte.</p>
<div id="logs"></div>
<script>
function r(){
    fetch('/api').then(r=>r.json()).then(d=>{
        document.getElementById('status').innerText=d.status;
        let h='';
        d.logs.forEach(l=>{
            let c=l.includes('✅')?'ok':l.includes('❌')?'err':'';
            h+='<div class="'+c+'">'+l+'</div>';
        });
        document.getElementById('logs').innerHTML=h;
        document.getElementById('logs').scrollTop=99999;
    });
}
setInterval(r,3000);r();
</script>
</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(HTML)

@app.route('/api')
def api():
    return jsonify(status=status, logs=logs)

# ── Démarrage automatique ──
threading.Thread(target=boucle_ia, daemon=True).start()
threading.Thread(target=self_ping, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

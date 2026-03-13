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
RENDER_URL = os.getenv("RENDER_URL", "")

genai.configure(api_key=os.getenv("GEMINI_KEY"))
model = genai.GenerativeModel('gemini-3-flash-preview')

logs = []
conn = None
status = "Démarrage..."
cycle_count = 0

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
    """Lit la variable cloud — gère les 2 formats de l'API"""
    global cycle_count
    cycle_count += 1

    try:
        url = f"https://clouddata.scratch.mit.edu/logs?projectid={PROJECT_ID}&limit=5&offset=0"
        r = http_requests.get(url, timeout=10)
        texte = r.text.strip()

        # Debug toutes les 10 lectures
        if cycle_count % 10 == 1:
            log(f"🔍 API brut ({len(texte)} chars) : {texte[:200]}")

        # FORMAT 1 : Tableau JSON [{...},{...}]
        if texte.startswith('['):
            data = json.loads(texte)
            for entry in data:
                if 'Messages sent' in entry.get('name', ''):
                    val = str(entry.get('value', '0')).split('.')[0]
                    if cycle_count % 10 == 1:
                        log(f"🔍 Valeur trouvée (JSON array) : {val}")
                    return val

        # FORMAT 2 : JSON ligne par ligne
        else:
            for line in texte.split('\n'):
                try:
                    d = json.loads(line)
                    if 'Messages sent' in d.get('name', ''):
                        val = str(d.get('value', '0')).split('.')[0]
                        if cycle_count % 10 == 1:
                            log(f"🔍 Valeur trouvée (ligne) : {val}")
                        return val
                except:
                    pass

        if cycle_count % 10 == 1:
            log(f"⚠️ Pas de 'Messages sent' trouvé dans la réponse")

    except Exception as e:
        log(f"❌ Erreur lecture API : {e}")

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
# BOUCLE IA
# ══════════════════════════════

def boucle_ia():
    global status
    time.sleep(2)

    for tentative in range(5):
        if do_connect():
            break
        log(f"🔄 Tentative {tentative+1}/5...")
        time.sleep(10)

    if not conn:
        status = "❌ Connexion impossible"
        return

    status = "✅ En ligne"
    last = ""
    log("🔄 Boucle IA démarrée !")

    while True:
        try:
            val = lire_variable()

            # Log la valeur quand elle change
            if val != "0" and val != last:
                log(f"📡 Nouvelle valeur détectée : {val}")
                log(f"📡 Premier caractère : '{val[0]}' — commence par 1 ? {val.startswith('1')}")

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
                log(f"📤 Encodé : {encoded}")

                conn.set_var("Messages sent", encoded)
                log(f"✅ Envoyé à Scratch !")
                status = "✅ En ligne"

            elif val.startswith("2") and val != last:
                # C'est une réponse déjà envoyée, on ignore
                last = val

            time.sleep(2)

        except Exception as e:
            log(f"❌ Erreur boucle : {e}")
            status = "🔄 Reconnexion..."
            time.sleep(5)
            do_connect()
            if conn:
                status = "✅ En ligne"

# ══════════════════════════════
# SELF-PING
# ══════════════════════════════

def self_ping():
    time.sleep(30)
    while True:
        try:
            if RENDER_URL:
                http_requests.get(RENDER_URL, timeout=10)
        except:
            pass
        time.sleep(300)

# ══════════════════════════════
# PAGE WEB
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
.debug { color: #666; }
p { font-size: 11px; color: #888; margin: 8px 0; }
</style>
</head>
<body>
<h1>🤖 IA Scratch</h1>
<div id="status">...</div>
<p>Tout est automatique. Ouvre Scratch, appuie ESPACE, pose ta question.</p>
<div id="logs"></div>
<script>
function r(){
    fetch('/api').then(r=>r.json()).then(d=>{
        document.getElementById('status').innerText=d.status;
        let h='';
        d.logs.forEach(l=>{
            let c='';
            if(l.includes('✅'))c='ok';
            else if(l.includes('❌'))c='err';
            else if(l.includes('🔍'))c='debug';
            h+='<div class="'+c+'">'+l+'</div>';
        });
        document.getElementById('logs').innerHTML=h;
        document.getElementById('logs').scrollTop=99999;
    });
}
setInterval(r,2000);r();
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

# ── Démarrage ──
threading.Thread(target=boucle_ia, daemon=True).start()
threading.Thread(target=self_ping, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

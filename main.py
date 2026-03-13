import os
import time
import json
import threading
import requests as http_requests
from flask import Flask, render_template_string, jsonify
import scratchattach as scratch
import google.generativeai as genai

app = Flask(__name__)

# ── Config ──
CHARS = " abcdefghijklmnopqrstuvwxyz0123456789.,!?@'\"()+-*/=:_éàè"
PROJECT_ID = os.getenv("SCRATCH_ID", "")
SCRATCH_USER = os.getenv("SCRATCH_USER", "")
SCRATCH_PASS = os.getenv("SCRATCH_PASS", "")

genai.configure(api_key=os.getenv("GEMINI_KEY"))
model = genai.GenerativeModel('gemini-3-flash-preview')

logs = []
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

def lire_variable():
    """Lit la variable cloud via l'API REST Scratch"""
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
        log(f"❌ Connexion échouée : {e}")
        conn = None
        return False

# ══════════════════════════════
# BOUCLE IA
# ══════════════════════════════

def boucle_ia():
    time.sleep(3)
    if not do_connect():
        log("❌ Impossible de démarrer")
        return

    last = ""
    log("🔄 Boucle IA démarrée — en attente de messages Scratch...")

    while True:
        try:
            val = lire_variable()

            if val.startswith("1") and len(val) > 2 and val != last:
                last = val

                # 1. Décoder le message de Scratch
                question = decode(val)
                log(f"📩 Question reçue : {question}")

                # 2. Demander à l'IA
                log("🤖 Gemini réfléchit...")
                res = model.generate_content(
                    "Réponds en français, très court, max 30 caractères, "
                    "utilise uniquement des lettres simples (a-z), "
                    "des chiffres et de la ponctuation basique. "
                    "Pas d'émoji, pas de markdown, pas de majuscules. "
                    "Question : " + question
                )
                reponse = res.text.strip()
                log(f"🤖 Réponse brute : {reponse}")

                # 3. Nettoyer (garder que les caractères supportés)
                reponse_clean = ''.join(
                    c for c in reponse.lower() if c in CHARS
                )[:40]
                log(f"🤖 Réponse nettoyée : {reponse_clean}")

                # 4. Encoder et envoyer à Scratch
                encoded = encode(reponse_clean)
                conn.set_var("Messages sent", encoded)
                log(f"📤 Envoyé à Scratch : {encoded}")
                log(f"✅ Scratch devrait afficher : {reponse_clean}")

            time.sleep(2)

        except Exception as e:
            log(f"❌ Erreur : {e}")
            time.sleep(5)
            do_connect()

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
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: monospace; background: #fff; padding: 20px;
       max-width: 500px; margin: auto; }
h1 { font-size: 18px; margin-bottom: 15px; }
#live { font-size: 20px; font-weight: bold; padding: 12px;
        text-align: center; border: 2px solid #000; margin-bottom: 5px; }
#decoded { font-size: 16px; text-align: center; padding: 8px;
           margin-bottom: 15px; }
#logs { border: 1px solid #ccc; padding: 8px; height: 350px;
        overflow-y: auto; font-size: 11px; background: #f9f9f9;
        line-height: 1.6; }
.ok { color: green; font-weight: bold; }
.err { color: red; font-weight: bold; }
p { font-size: 12px; color: #666; margin: 10px 0; line-height: 1.5; }
</style>
</head>
<body>

<h1>🤖 IA Scratch — En ligne</h1>

<div id="live">chargement...</div>
<div id="decoded"></div>

<p>
    Ouvre <a href="https://scratch.mit.edu/projects/PROJ_ID" target="_blank">
    ton projet Scratch</a>, clique ▶️, appuie ESPACE et pose une question !
</p>

<h2 style="font-size:14px;margin:10px 0 5px">📋 Logs</h2>
<div id="logs"></div>

<script>
function refresh() {
    fetch('/live').then(r=>r.json()).then(d=>{
        document.getElementById('live').innerText = d.raw;
        document.getElementById('live').style.background =
            d.prefix=='1'?'#e3f2fd':d.prefix=='2'?'#e8f5e9':'#f5f5f5';
        let lbl = d.prefix=='1'?'📤 SCRATCH dit : ':d.prefix=='2'?'🤖 IA dit : ':'';
        document.getElementById('decoded').innerText = lbl + d.decoded;
        document.getElementById('decoded').style.color =
            d.prefix=='1'?'#1565c0':d.prefix=='2'?'#2e7d32':'#333';
    });
    fetch('/logs').then(r=>r.json()).then(d=>{
        let h='';
        d.logs.forEach(l=>{
            let c=l.includes('✅')?'ok':l.includes('❌')?'err':'';
            h+='<div class="'+c+'">'+l+'</div>';
        });
        document.getElementById('logs').innerHTML=h;
        document.getElementById('logs').scrollTop=99999;
    });
}
setInterval(refresh, 2000);
refresh();
</script>
</body>
</html>
""".replace("PROJ_ID", PROJECT_ID)

@app.route('/')
def home():
    return render_template_string(HTML)

@app.route('/live')
def live():
    val = lire_variable()
    prefix = val[0] if val else ""
    decoded = ""
    if prefix in ('1', '2') and len(val) > 2:
        try:
            decoded = decode(val)
        except:
            decoded = "?"
    return jsonify(raw=val, decoded=decoded, prefix=prefix)

@app.route('/logs')
def get_logs():
    return jsonify(logs=logs)

# ── Démarrage ──
threading.Thread(target=boucle_ia, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

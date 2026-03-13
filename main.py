import os
import time
import json
import threading
import requests as http_requests
from flask import Flask, request, jsonify, render_template_string
import scratchattach as scratch
import google.generativeai as genai

app = Flask(__name__)

CHARS = " abcdefghijklmnopqrstuvwxyz0123456789.,!?@'\"()+-*/=:_éàè"
PROJECT_ID = os.getenv("SCRATCH_ID", "")
SCRATCH_USER = os.getenv("SCRATCH_USER", "")
SCRATCH_PASS = os.getenv("SCRATCH_PASS", "")

logs = []
conn = None

genai.configure(api_key=os.getenv("GEMINI_KEY"))
model = genai.GenerativeModel('gemini-3-flash-preview')

def log(msg):
    t = time.strftime("%H:%M:%S")
    entry = f"[{t}] {msg}"
    logs.append(entry)
    if len(logs) > 100: logs.pop(0)
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
# BOUCLE IA AUTOMATIQUE
# ══════════════════════════════

def boucle_ia():
    time.sleep(3)
    if not do_connect():
        log("❌ Boucle IA impossible")
        return

    last = ""
    log("🔄 Boucle IA démarrée !")

    while True:
        try:
            # Lire via API REST
            url = f"https://clouddata.scratch.mit.edu/logs?projectid={PROJECT_ID}&limit=5&offset=0"
            r = http_requests.get(url, timeout=10)
            val = "0"
            for line in r.text.strip().split('\n'):
                try:
                    d = json.loads(line)
                    if 'Messages sent' in d.get('name', ''):
                        val = str(d.get('value', '0')).split('.')[0]
                        break
                except:
                    pass

            if val.startswith("1") and len(val) > 2 and val != last:
                last = val
                question = decode(val)
                log(f"📩 Question : {question}")

                res = model.generate_content(
                    "Réponds en français, très court, max 30 caractères, "
                    "pas d'émoji, pas de markdown : " + question
                )
                reponse = ''.join(
                    c for c in res.text.strip().lower() if c in CHARS
                )[:40]
                log(f"🤖 Réponse : {reponse}")

                encoded = encode(reponse)
                conn.set_var("Messages sent", encoded)
                log(f"📤 Envoyé : {encoded}")

            time.sleep(2)

        except Exception as e:
            log(f"❌ Erreur boucle : {e}")
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
        text-align: center; border: 2px solid #000; margin-bottom: 10px; }
#decoded { font-size: 16px; text-align: center; padding: 6px;
           color: blue; margin-bottom: 15px; }
#logs { border: 1px solid #ccc; padding: 8px; height: 200px;
        overflow-y: auto; font-size: 11px; background: #f9f9f9; }
.ok { color: green; font-weight: bold; }
.err { color: red; font-weight: bold; }
p { font-size: 12px; color: #666; margin: 10px 0; }
</style>
</head>
<body>

<h1>🤖 IA Scratch — En ligne</h1>

<div id="live">chargement...</div>
<div id="decoded"></div>

<p>
    La boucle IA tourne automatiquement.<br>
    Ouvre <a href="https://scratch.mit.edu/projects/PROJ_ID" target="_blank">
    ton projet Scratch ↗</a>, clique ▶️, appuie ESPACE et pose une question !
</p>

<h2 style="font-size:14px;margin:10px 0 5px">📋 Logs</h2>
<div id="logs"></div>

<script>
function refresh() {
    fetch('/live').then(r=>r.json()).then(d=>{
        document.getElementById('live').innerText = d.raw;
        document.getElementById('live').style.background =
            d.prefix=='1'?'#e3f2fd':d.prefix=='2'?'#e8f5e9':'#f5f5f5';
        let lbl = d.prefix=='1'?'📤 SCRATCH: ':d.prefix=='2'?'🤖 IA: ':'';
        document.getElementById('decoded').innerText = lbl + d.decoded;
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
setInterval(refresh, 3000);
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
    try:
        url = f"https://clouddata.scratch.mit.edu/logs?projectid={PROJECT_ID}&limit=5&offset=0"
        r = http_requests.get(url, timeout=10)
        for line in r.text.strip().split('\n'):
            try:
                d = json.loads(line)
                if 'Messages sent' in d.get('name', ''):
                    val = str(d.get('value', '0')).split('.')[0]
                    prefix = val[0] if val else ""
                    decoded = ""
                    if prefix in ('1','2') and len(val) > 2:
                        try: decoded = decode(val)
                        except: decoded = "?"
                    return jsonify(raw=val, decoded=decoded, prefix=prefix)
            except:
                pass
        return jsonify(raw="0", decoded="", prefix="0")
    except Exception as e:
        return jsonify(raw="erreur", decoded=str(e), prefix="")

@app.route('/logs')
def get_logs():
    return jsonify(logs=logs)

# Démarrer
threading.Thread(target=boucle_ia, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

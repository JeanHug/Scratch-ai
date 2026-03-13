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

def log(msg):
    t = time.strftime("%H:%M:%S")
    entry = f"[{t}] {msg}"
    logs.append(entry)
    if len(logs) > 200:
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
        texte = r.text.strip()

        if texte.startswith('['):
            data = json.loads(texte)
            for entry in data:
                if 'Messages sent' in entry.get('name', ''):
                    return str(entry.get('value', '0')).split('.')[0]
        else:
            for line in texte.split('\n'):
                try:
                    d = json.loads(line)
                    if 'Messages sent' in d.get('name', ''):
                        return str(d.get('value', '0')).split('.')[0]
                except:
                    pass
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

    # IMPORTANT : lire la valeur actuelle et l'ignorer
    # pour ne pas traiter un vieux message
    old_val = lire_variable()
    last = old_val
    log(f"🔄 Valeur actuelle ignorée : {old_val}")
    if old_val.startswith(("1","2")) and len(old_val) > 2:
        try:
            log(f"🔄 (c'était : '{decode(old_val)}')")
        except:
            pass

    status = "✅ En ligne — en attente"
    log("✅ Boucle IA prête — envoie un message depuis Scratch !")

    while True:
        try:
            val = lire_variable()
            log(f"👁️ Lu : {val} (last={last})")

            # Nouveau message détecté
            if val.startswith("1") and len(val) > 2 and val != last:
                last = val

                # ÉTAPE 1 : Décoder
                log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                log(f"📡 ÉTAPE 1 — Message brut reçu : {val}")
                question = decode(val)
                log(f"📖 ÉTAPE 2 — Message décodé : '{question}'")

                # ÉTAPE 3 : Envoyer à l'IA
                log(f"🤖 ÉTAPE 3 — Envoi à Gemini...")
                try:
                    res = model.generate_content(
                        "Réponds en français, très court, max 30 caractères, "
                        "pas d'émoji, pas de markdown, pas de majuscules : " + question
                    )
                    reponse_brute = res.text.strip()
                    log(f"🤖 ÉTAPE 4 — Réponse brute de l'IA : '{reponse_brute}'")
                except Exception as e:
                    log(f"❌ ERREUR IA : {e}")
                    status = "✅ En ligne — en attente"
                    continue

                # ÉTAPE 5 : Nettoyer
                reponse_clean = ''.join(
                    c for c in reponse_brute.lower() if c in CHARS
                )[:40]
                log(f"🧹 ÉTAPE 5 — Réponse nettoyée : '{reponse_clean}'")

                if not reponse_clean:
                    log("⚠️ Réponse vide après nettoyage !")
                    status = "✅ En ligne — en attente"
                    continue

                # ÉTAPE 6 : Encoder
                encoded = encode(reponse_clean)
                log(f"🔢 ÉTAPE 6 — Réponse encodée : {encoded}")

                # ÉTAPE 7 : Envoyer à Scratch
                log(f"📤 ÉTAPE 7 — Envoi à Scratch...")
                try:
                    conn.set_var("Messages sent", encoded)
                    log(f"✅ ÉTAPE 8 — Envoyé à Scratch !")
                except Exception as e:
                    log(f"❌ ERREUR envoi Scratch : {e}")
                    log("🔄 Reconnexion...")
                    do_connect()
                    if conn:
                        conn.set_var("Messages sent", encoded)
                        log(f"✅ ÉTAPE 8 — Envoyé après reconnexion !")
                    else:
                        log(f"❌ Impossible d'envoyer")
                        continue

                # ÉTAPE 9 : Vérifier
                time.sleep(2)
                verif = lire_variable()
                log(f"🔍 ÉTAPE 9 — Vérification : variable = {verif}")
                if verif == encoded:
                    log(f"✅ ÉTAPE 10 — Scratch a reçu : '{reponse_clean}'")
                else:
                    log(f"⚠️ ÉTAPE 10 — Variable différente : {verif}")
                    if verif.startswith("2"):
                        log(f"⚠️ (mais commence par 2, probablement OK)")
                    else:
                        log(f"❌ Scratch a peut-être écrasé la réponse")

                log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                status = "✅ En ligne — en attente"

            elif val.startswith("2") and val != last:
                last = val
                log(f"ℹ️ Réponse IA encore présente : {val}")

            time.sleep(3)

        except Exception as e:
            log(f"❌ Erreur boucle : {e}")
            status = "🔄 Reconnexion..."
            time.sleep(5)
            do_connect()
            if conn:
                status = "✅ En ligne — en attente"

def self_ping():
    time.sleep(30)
    while True:
        try:
            if RENDER_URL:
                http_requests.get(RENDER_URL, timeout=10)
        except:
            pass
        time.sleep(300)

HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>IA Scratch</title>
<style>
body { font-family: monospace; background: #fff; padding: 20px;
       max-width: 600px; margin: auto; }
h1 { font-size: 18px; margin-bottom: 15px; }
#status { font-size: 16px; padding: 10px; border: 2px solid #000;
          margin-bottom: 10px; text-align: center; }
#logs { border: 1px solid #ccc; padding: 8px; height: 500px;
        overflow-y: auto; font-size: 11px; background: #f9f9f9;
        line-height: 1.6; }
.ok { color: green; font-weight: bold; }
.err { color: red; font-weight: bold; }
.step { color: #1565c0; }
.sep { color: #999; }
.eye { color: #888; font-size: 10px; }
p { font-size: 11px; color: #888; margin: 8px 0; }
</style>
</head>
<body>
<h1>🤖 IA Scratch</h1>
<div id="status">...</div>
<p>Ouvre Scratch, appuie ESPACE, pose ta question. Les étapes s'affichent ici :</p>
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
            else if(l.includes('ÉTAPE'))c='step';
            else if(l.includes('━'))c='sep';
            else if(l.includes('👁'))c='eye';
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

threading.Thread(target=boucle_ia, daemon=True).start()
threading.Thread(target=self_ping, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

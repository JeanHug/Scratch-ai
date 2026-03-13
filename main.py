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

MODELS = [
    'gemini-3-flash-preview',
    'gemini-3.1-flash-lite-preview',
    'gemini-2.5-flash-preview',
    'gemini-2.0-flash',
    'gemma-3-27b-it',
    'gemma-3n-e4b-it',
]

logs = []
conn = None
status = "Démarrage..."
last_val = ""
ia_thread = None
working_model = None

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
    if len(s) % 2 != 0:
        s = s[:-1]
    for i in range(0, len(s), 2):
        try:
            idx = int(s[i:i+2])
        except:
            continue
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
        log(f"❌ Erreur lecture : {e}")
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
# IA AVEC FALLBACK
# ══════════════════════════════

def demander_ia(question):
    global working_model

    # Si un modèle marchait avant, l'essayer en premier
    if working_model:
        try:
            m = genai.GenerativeModel(working_model)
            res = m.generate_content(
                "Réponds en français."
                "pas d'émoji, pas de markdown, pas de majuscules : " + question
            )
            log(f"✅ IA OK ({working_model})")
            return res.text.strip()
        except Exception as e:
            log(f"⚠️ {working_model} a planté : {e}")
            working_model = None

    # Essayer chaque modèle
    for model_name in MODELS:
        try:
            log(f"🤖 Essai {model_name}...")
            m = genai.GenerativeModel(model_name)
            res = m.generate_content(
                "Réponds en français. "
                "pas d'émoji, pas de markdown, pas de majuscules : " + question
            )
            log(f"✅ IA OK avec {model_name}")
            working_model = model_name
            return res.text.strip()
        except Exception as e:
            log(f"❌ {model_name} échoué : {e}")

    log("❌ TOUS LES MODÈLES ONT ÉCHOUÉ")
    return None

# ══════════════════════════════
# TRAITEMENT D'UN MESSAGE
# ══════════════════════════════

def traiter_message(val):
    global conn

    log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log(f"📡 ÉTAPE 1 — Reçu : {val}")

    question = decode(val)
    log(f"📖 ÉTAPE 2 — Décodé : '{question}'")

    log("🤖 ÉTAPE 3 — Envoi à l'IA...")
    reponse_brute = demander_ia(question)

    if not reponse_brute:
        log("❌ Pas de réponse IA")
        log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        return False

    log(f"🤖 ÉTAPE 4 — Réponse brute : '{reponse_brute}'")

    reponse_clean = ''.join(
        c for c in reponse_brute.lower() if c in CHARS
    )[120]
    log(f"🧹 ÉTAPE 5 — Nettoyée : '{reponse_clean}'")

    if not reponse_clean:
        log("⚠️ Réponse vide après nettoyage")
        log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        return False

    encoded = encode(reponse_clean)
    log(f"🔢 ÉTAPE 6 — Encodée : {encoded}")

    log("📤 ÉTAPE 7 — Envoi à Scratch...")
    for tentative in range(3):
        try:
            conn.set_var("Messages sent", encoded)
            log("✅ ÉTAPE 8 — Envoyé !")
            break
        except Exception as e:
            log(f"❌ Envoi échoué (tentative {tentative+1}) : {e}")
            do_connect()

    time.sleep(2)
    verif = lire_variable()
    log(f"🔍 ÉTAPE 9 — Vérification : {verif}")
    if verif == encoded:
        log(f"✅ ÉTAPE 10 — Scratch a reçu : '{reponse_clean}'")
    else:
        log(f"⚠️ Variable différente : {verif}")
    log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return True

# ══════════════════════════════
# BOUCLE PRINCIPALE
# ══════════════════════════════

def boucle_ia():
    global status, last_val

    time.sleep(2)

    for i in range(5):
        if do_connect():
            break
        log(f"🔄 Tentative {i+1}/5...")
        time.sleep(10)

    if not conn:
        status = "❌ Connexion impossible"
        return

    old = lire_variable()
    last_val = old
    log(f"🔄 Valeur initiale ignorée : {old}")

    status = "✅ En ligne"
    log("✅ Boucle IA prête !")

    while True:
        try:
            val = lire_variable()

            if val.startswith("1") and len(val) > 4 and val != last_val:
                last_val = val
                status = "🤖 Traitement..."
                traiter_message(val)
                status = "✅ En ligne"
            elif val != last_val:
                last_val = val

            time.sleep(3)

        except Exception as e:
            log(f"❌ Erreur boucle : {e}")
            status = "🔄 Reconnexion..."
            time.sleep(5)
            do_connect()
            if conn:
                status = "✅ En ligne"

# ══════════════════════════════
# WATCHDOG — vérifie que le thread tourne
# ══════════════════════════════

def verifier_thread():
    global ia_thread
    if ia_thread is None or not ia_thread.is_alive():
        log("🔄 Thread mort → redémarrage !")
        ia_thread = threading.Thread(target=boucle_ia, daemon=True)
        ia_thread.start()
        return "relancé"
    return "actif"

# ══════════════════════════════
# SELF-PING
# ══════════════════════════════

def self_ping():
    time.sleep(30)
    while True:
        try:
            if RENDER_URL:
                # Ping /tick au lieu de / pour vérifier le thread
                http_requests.get(f"{RENDER_URL}/tick", timeout=10)
        except:
            pass
        time.sleep(240)  # 4 minutes

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
       max-width: 600px; margin: auto; }
h1 { font-size: 18px; margin-bottom: 15px; }
#status { font-size: 16px; padding: 10px; border: 2px solid #000;
          margin-bottom: 5px; text-align: center; }
#thread { font-size: 12px; padding: 5px; border: 1px solid #ccc;
          margin-bottom: 10px; text-align: center; color: #666; }
#logs { border: 1px solid #ccc; padding: 8px; height: 500px;
        overflow-y: auto; font-size: 11px; background: #f9f9f9;
        line-height: 1.6; }
.ok { color: green; font-weight: bold; }
.err { color: red; font-weight: bold; }
.step { color: #1565c0; }
.sep { color: #ccc; }
.eye { color: #aaa; font-size: 10px; }
.warn { color: orange; }
p { font-size: 11px; color: #888; margin: 8px 0; }
</style>
</head>
<body>
<h1>🤖 IA Scratch</h1>
<div id="status">...</div>
<div id="thread">...</div>
<p>Tout est automatique. Ouvre Scratch, appuie ESPACE, pose ta question.</p>
<div id="logs"></div>
<script>
function r(){
    fetch('/api').then(r=>r.json()).then(d=>{
        document.getElementById('status').innerText=d.status;
        document.getElementById('thread').innerText=
            'Thread: '+d.thread+' | Modèle: '+(d.model||'aucun')+' | Cycles: '+d.cycles;
        let h='';
        d.logs.forEach(l=>{
            let c='';
            if(l.includes('✅'))c='ok';
            else if(l.includes('❌'))c='err';
            else if(l.includes('ÉTAPE'))c='step';
            else if(l.includes('━'))c='sep';
            else if(l.includes('⚠'))c='warn';
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
    t = verifier_thread()
    return jsonify(
        status=status,
        logs=logs,
        thread=t,
        model=working_model,
        cycles=len([l for l in logs if 'ÉTAPE 1' in l])
    )

@app.route('/tick')
def tick():
    t = verifier_thread()
    return jsonify(status="ok", thread=t)

@app.route('/logs')
def get_logs():
    return jsonify(logs=logs)

# ── Démarrage ──
ia_thread = threading.Thread(target=boucle_ia, daemon=True)
ia_thread.start()
threading.Thread(target=self_ping, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

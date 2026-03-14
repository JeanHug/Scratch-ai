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

# ══════════════════════════════
# MÉMOIRE DEVOIRGPT
# ══════════════════════════════
etat = "attente"      # "attente" → attend niveau+sujet
                       # "question_posee" → attend la réponse de l'élève
memoire = {
    "niveau": "",
    "sujet": "",
    "question": ""
}

def log(msg):
    t = time.strftime("%H:%M:%S")
    entry = f"[{t}] {msg}"
    logs.append(entry)
    if len(logs) > 200:
        logs.pop(0)
    print(entry, flush=True)

def encode(text):
    try:
        r = "2"
        for c in text.lower():
            if c in CHARS:
                r += str(CHARS.index(c) + 1).zfill(2)
        return r
    except Exception as e:
        log(f"❌ Erreur encode : {e}")
        return "2"

def decode(s):
    try:
        s = str(s)
        if len(s) < 3:
            return ""
        s = s[1:]
        if len(s) % 2 != 0:
            s = s[:-1]
        t = ""
        for i in range(0, len(s), 2):
            try:
                idx = int(s[i:i+2])
                if 1 <= idx <= len(CHARS):
                    t += CHARS[idx - 1]
            except:
                continue
        return t
    except Exception as e:
        log(f"❌ Erreur decode : {e}")
        return ""

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
        if conn:
            try:
                conn.disconnect()
            except:
                pass
            conn = None
        log("🔌 Connexion Scratch...")
        s = scratch.login(SCRATCH_USER, SCRATCH_PASS)
        conn = s.connect_cloud(PROJECT_ID)
        time.sleep(1)
        log("✅ Connecté !")
        return True
    except Exception as e:
        log(f"❌ Connexion : {e}")
        conn = None
        return False

def envoyer_scratch(valeur):
    global conn
    for tentative in range(3):
        try:
            if not conn:
                do_connect()
            if conn:
                conn.set_var("Messages sent", str(valeur))
                return True
        except Exception as e:
            log(f"❌ Envoi tentative {tentative+1} : {e}")
            conn = None
            time.sleep(2)
            do_connect()
    return False

def demander_ia(prompt_complet):
    global working_model

    if working_model:
        try:
            m = genai.GenerativeModel(working_model)
            res = m.generate_content(prompt_complet)
            log(f"✅ IA OK ({working_model})")
            return res.text.strip()
        except Exception as e:
            log(f"⚠️ {working_model} a planté : {e}")
            working_model = None

    for model_name in MODELS:
        try:
            log(f"🤖 Essai {model_name}...")
            m = genai.GenerativeModel(model_name)
            res = m.generate_content(prompt_complet)
            log(f"✅ IA OK avec {model_name}")
            working_model = model_name
            return res.text.strip()
        except Exception as e:
            log(f"❌ {model_name} échoué : {e}")

    return None

def reset_memoire():
    global etat, memoire
    etat = "attente"
    memoire = {"niveau": "", "sujet": "", "question": ""}
    log("🧹 Mémoire effacée — retour en attente")

# ══════════════════════════════
# TRAITEMENT MESSAGE
# ══════════════════════════════

def traiter_message(val):
    global etat, memoire

    log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log(f"📡 Reçu brut : {val}")
    log(f"📡 État actuel : {etat}")

    texte_complet = decode(val)
    if not texte_complet:
        log("❌ Décodage vide !")
        log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        return False

    log(f"📖 Décodé : '{texte_complet}'")

    # ════════════════════════════
    # MODE 1 : On attend niveau + sujet
    # ════════════════════════════
    if etat == "attente":
        # Premier caractère = niveau, reste = sujet
        niveau = texte_complet[0]
        sujet = texte_complet[1:].strip()

        log(f"📚 Niveau : {niveau}ème")
        log(f"📚 Sujet : {sujet}")

        if not sujet:
            log("❌ Sujet vide !")
            log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            return False

        # Demander une question à l'IA
        prompt = (
            f"Tu es un professeur. "
            f"Génère UNE SEULE question courte et précise pour un élève de {niveau}ème "
            f"sur le sujet : {sujet}. "
            f"Réponds UNIQUEMENT par la question, rien d'autre. "
            f"En français. Maximum 100 caractères."
        )

        log("🤖 Demande d'une question à l'IA...")
        reponse_brute = demander_ia(prompt)

        if not reponse_brute:
            log("❌ Pas de réponse IA")
            log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            return False

        log(f"🤖 Question brute : '{reponse_brute}'")

        question_clean = ''.join(
            c for c in reponse_brute.lower() if c in CHARS
        )[:120]
        log(f"🧹 Question nettoyée : '{question_clean}'")

        if not question_clean:
            log("⚠️ Question vide après nettoyage")
            log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            return False

        # Sauvegarder en mémoire
        memoire["niveau"] = niveau
        memoire["sujet"] = sujet
        memoire["question"] = question_clean
        etat = "question_posee"

        log(f"💾 Mémoire : niveau={niveau}, sujet={sujet}")
        log(f"💾 Question mémorisée : '{question_clean}'")

        # Envoyer la question à Scratch
        encoded = encode(question_clean)
        log(f"🔢 Encodée : {encoded}")
        log("📤 Envoi de la question à Scratch...")

        ok = envoyer_scratch(encoded)
        if ok:
            log("✅ Question envoyée ! En attente de la réponse de l'élève...")
        else:
            log("❌ Échec envoi")
            reset_memoire()

        log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        return ok

    # ════════════════════════════
    # MODE 2 : On attend la réponse de l'élève
    # ════════════════════════════
    elif etat == "question_posee":
        reponse_eleve = texte_complet
        log(f"📝 Réponse de l'élève : '{reponse_eleve}'")
        log(f"💾 Question était : '{memoire['question']}'")
        log(f"💾 Niveau : {memoire['niveau']}ème | Sujet : {memoire['sujet']}")

        # Demander à l'IA si c'est vrai ou faux
        prompt = (
            f"Voici une question posée à un élève de {memoire['niveau']}ème "
            f"sur le sujet {memoire['sujet']} : "
            f"{memoire['question']} "
            f"Voici la réponse de l'élève : {reponse_eleve} "
            f"Cette réponse est-elle correcte ? "
            f"Réponds UNIQUEMENT par le mot vrai ou le mot faux, "
            f"rien d'autre, pas de majuscule, pas de ponctuation."
        )

        log("🤖 Vérification par l'IA...")
        reponse_brute = demander_ia(prompt)

        if not reponse_brute:
            log("❌ Pas de réponse IA")
            reset_memoire()
            log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            return False

        log(f"🤖 Réponse brute : '{reponse_brute}'")

        # Nettoyer : garder juste "vrai" ou "faux"
        reponse_lower = reponse_brute.lower().strip()
        if "vrai" in reponse_lower:
            resultat = "vrai"
        elif "faux" in reponse_lower:
            resultat = "faux"
        else:
            resultat = ''.join(
                c for c in reponse_lower if c in CHARS
            )[:120]

        log(f"✏️ Résultat : '{resultat}'")

        # Envoyer à Scratch
        encoded = encode(resultat)
        log(f"🔢 Encodé : {encoded}")
        log("📤 Envoi du résultat à Scratch...")

        ok = envoyer_scratch(encoded)
        if ok:
            log(f"✅ Résultat envoyé : {resultat}")
        else:
            log("❌ Échec envoi")

        # Remettre à zéro
        reset_memoire()
        log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        return ok

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
    reset_memoire()

    status = "✅ En ligne"
    log("✅ DevoirGPT prêt !")

    while True:
        try:
            val = lire_variable()

            if val.startswith("1") and len(val) > 4 and val != last_val:
                last_val = val
                status = f"🤖 Traitement ({etat})..."
                try:
                    traiter_message(val)
                except Exception as e:
                    log(f"❌ Erreur traitement : {e}")
                    do_connect()
                status = f"✅ En ligne ({etat})"
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

def verifier_thread():
    global ia_thread
    if ia_thread is None or not ia_thread.is_alive():
        log("🔄 Thread relancé !")
        ia_thread = threading.Thread(target=boucle_ia, daemon=True)
        ia_thread.start()
        return "relancé"
    return "actif"

def self_ping():
    time.sleep(30)
    while True:
        try:
            if RENDER_URL:
                http_requests.get(f"{RENDER_URL}/tick", timeout=10)
        except:
            pass
        time.sleep(240)

# ══════════════════════════════
# PAGE WEB
# ══════════════════════════════

HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>DevoirGPT</title>
<style>
body { font-family: monospace; background: #fff; padding: 20px;
       max-width: 600px; margin: auto; }
h1 { font-size: 18px; margin-bottom: 15px; }
#status { font-size: 16px; padding: 10px; border: 2px solid #000;
          margin-bottom: 5px; text-align: center; }
#thread { font-size: 12px; padding: 5px; border: 1px solid #ccc;
          margin-bottom: 5px; text-align: center; color: #666; }
#mem { font-size: 12px; padding: 5px; border: 1px solid #ccc;
       margin-bottom: 10px; text-align: center; color: #336; }
#logs { border: 1px solid #ccc; padding: 8px; height: 500px;
        overflow-y: auto; font-size: 11px; background: #f9f9f9;
        line-height: 1.6; }
.ok { color: green; font-weight: bold; }
.err { color: red; font-weight: bold; }
.step { color: #1565c0; }
.sep { color: #ccc; }
.warn { color: orange; }
.mem { color: purple; }
p { font-size: 11px; color: #888; margin: 8px 0; }
</style>
</head>
<body>
<h1>📚 DevoirGPT</h1>
<div id="status">...</div>
<div id="thread">...</div>
<div id="mem">...</div>
<p>Scratch envoie : niveau + sujet → IA génère une question → l'élève répond → IA corrige</p>
<div id="logs"></div>
<script>
function r(){
    fetch('/api').then(r=>r.json()).then(d=>{
        document.getElementById('status').innerText=d.status;
        document.getElementById('thread').innerText=
            'Thread: '+d.thread+' | Modèle: '+(d.model||'aucun');
        document.getElementById('mem').innerText=
            'État: '+d.etat+' | Niveau: '+(d.memoire.niveau||'-')+
            ' | Sujet: '+(d.memoire.sujet||'-')+
            ' | Question: '+(d.memoire.question||'-').substring(0,40);
        let h='';
        d.logs.forEach(l=>{
            let c='';
            if(l.includes('✅'))c='ok';
            else if(l.includes('❌'))c='err';
            else if(l.includes('ÉTAPE')||l.includes('📡')||l.includes('📖'))c='step';
            else if(l.includes('━'))c='sep';
            else if(l.includes('⚠'))c='warn';
            else if(l.includes('💾'))c='mem';
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
        etat=etat,
        memoire=memoire
    )

@app.route('/tick')
def tick():
    t = verifier_thread()
    return jsonify(status="ok", thread=t)

ia_thread = threading.Thread(target=boucle_ia, daemon=True)
ia_thread.start()
threading.Thread(target=self_ping, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

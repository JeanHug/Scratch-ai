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
CEREBRAS_KEY = os.getenv("CEREBRAS_KEY", "")
GROQ_KEY = os.getenv("GROQ_KEY", "")

genai.configure(api_key=os.getenv("GEMINI_KEY"))

logs = []
conn = None
session_obj = None
status = "Démarrage..."
last_val = ""
ia_thread = None
working_provider = None
modeles_status = {}

etat = "attente"
memoire = {
    "niveau": "",
    "sujet": "",
    "questions": [],
    "index": 0,
    "question_actuelle": "",
    "timestamp": 0
}

TIMEOUT = 120

def log(msg):
    t = time.strftime("%H:%M:%S")
    entry = f"[{t}] {msg}"
    logs.append(entry)
    if len(logs) > 200:
        logs.pop(0)
    print(entry, flush=True)

def encode(text):
    try:
        text = text.lower().strip()
        r = "2"
        for c in text:
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

def login_scratch():
    global session_obj
    try:
        log("🔑 Login Scratch...")
        session_obj = scratch.login(SCRATCH_USER, SCRATCH_PASS)
        log("✅ Login OK !")
        return True
    except Exception as e:
        log(f"❌ Login échoué : {e}")
        session_obj = None
        return False

def connecter_cloud():
    global conn
    try:
        if conn:
            try:
                conn.disconnect()
            except:
                pass
            conn = None
        if not session_obj:
            log("❌ Pas de session")
            return False
        log("🔌 Connexion cloud...")
        conn = session_obj.connect_cloud(PROJECT_ID)
        time.sleep(1)
        log("✅ Cloud connecté !")
        return True
    except Exception as e:
        log(f"❌ Cloud échoué : {e}")
        conn = None
        return False

def login_et_cloud():
    """Login complet + cloud — utilisé en dernier recours"""
    global session_obj, conn
    try:
        if conn:
            try:
                conn.disconnect()
            except:
                pass
            conn = None
        log("🔑🔌 Login complet + cloud...")
        session_obj = scratch.login(SCRATCH_USER, SCRATCH_PASS)
        conn = session_obj.connect_cloud(PROJECT_ID)
        time.sleep(1)
        log("✅ Login + cloud OK !")
        return True
    except Exception as e:
        log(f"❌ Login complet échoué : {e}")
        conn = None
        return False

def envoyer_scratch(valeur):
    """Envoie avec 5 tentatives : reconnexion cloud → login complet → vérification"""
    global conn
    valeur_str = str(valeur)

    for tentative in range(5):
        try:
            # Tentatives 1-3 : reconnexion cloud seulement
            # Tentatives 4-5 : login complet
            if tentative >= 3:
                log(f"🔑 Tentative {tentative+1} : login complet...")
                login_et_cloud()
            elif tentative > 0 or not conn:
                log(f"🔌 Tentative {tentative+1} : reconnexion cloud...")
                connecter_cloud()

            if not conn:
                log(f"❌ Tentative {tentative+1} : pas de connexion")
                time.sleep(2)
                continue

            conn.set_var("Messages sent", valeur_str)
            log(f"📤 Tentative {tentative+1} : valeur écrite")

            # Vérifier 3 fois avec délai
            for verif_try in range(3):
                time.sleep(2)
                verif = lire_variable()
                if verif == valeur_str:
                    log(f"✅ Vérifié (essai {verif_try+1}) : Scratch a reçu !")
                    return True
                log(f"⚠️ Vérif {verif_try+1} : attendu {valeur_str[:15]}..., lu {verif[:15]}...")

            log(f"❌ Tentative {tentative+1} : vérification échouée")
            conn = None

        except Exception as e:
            log(f"❌ Tentative {tentative+1} exception : {e}")
            conn = None
            time.sleep(2)

    log("❌❌❌ ÉCHEC TOTAL après 5 tentatives")
    return False

# ══════════════════════════════
# ROUTEUR IA
# ══════════════════════════════

def appeler_cerebras(prompt, model_name):
    url = "https://api.cerebras.ai/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CEREBRAS_KEY}"
    }
    data = {
        "model": model_name,
        "stream": False,
        "max_tokens": 2048,
        "temperature": 0.7,
        "top_p": 0.8,
        "messages": [{"role": "user", "content": prompt}]
    }
    r = http_requests.post(url, headers=headers, json=data, timeout=30)
    if r.status_code != 200:
        raise Exception(f"HTTP {r.status_code}: {r.text[:200]}")
    result = r.json()
    return result["choices"][0]["message"]["content"].strip()

def appeler_groq(prompt, model_name):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GROQ_KEY}"
    }
    data = {
        "model": model_name,
        "max_tokens": 2048,
        "temperature": 0.7,
        "messages": [{"role": "user", "content": prompt}]
    }
    r = http_requests.post(url, headers=headers, json=data, timeout=30)
    if r.status_code != 200:
        raise Exception(f"HTTP {r.status_code}: {r.text[:200]}")
    result = r.json()
    return result["choices"][0]["message"]["content"].strip()

def appeler_gemini(prompt, model_name):
    m = genai.GenerativeModel(model_name)
    res = m.generate_content(prompt)
    return res.text.strip()

TOUS_LES_MODELES = [
    {"nom": "cerebras-qwen", "fn": appeler_cerebras, "model": "qwen-3-235b-a22b-instruct-2507"},
    {"nom": "cerebras-llama", "fn": appeler_cerebras, "model": "llama3.1-8b"},
    {"nom": "groq-llama", "fn": appeler_groq, "model": "llama-3.1-8b-instant"},
    {"nom": "gemini-3-flash", "fn": appeler_gemini, "model": "gemini-3-flash-preview"},
    {"nom": "gemini-3.1-lite", "fn": appeler_gemini, "model": "gemini-3.1-flash-lite-preview"},
    {"nom": "gemini-2.5-flash", "fn": appeler_gemini, "model": "gemini-2.5-flash-preview"},
    {"nom": "gemini-2.0-flash", "fn": appeler_gemini, "model": "gemini-2.0-flash"},
    {"nom": "gemma-3-27b", "fn": appeler_gemini, "model": "gemma-3-27b-it"},
    {"nom": "gemma-3n-e4b", "fn": appeler_gemini, "model": "gemma-3n-e4b-it"},
]

def demander_ia(prompt_complet):
    global working_provider, modeles_status

    if working_provider:
        for m in TOUS_LES_MODELES:
            if m["nom"] == working_provider:
                try:
                    result = m["fn"](prompt_complet, m["model"])
                    log(f"✅ IA OK ({m['nom']})")
                    modeles_status[m["nom"]] = {"status": "✅ OK", "time": time.strftime("%H:%M:%S")}
                    return result
                except Exception as e:
                    log(f"⚠️ {m['nom']} a planté : {e}")
                    modeles_status[m["nom"]] = {"status": f"❌ {str(e)[:50]}", "time": time.strftime("%H:%M:%S")}
                    working_provider = None
                break

    for m in TOUS_LES_MODELES:
        try:
            log(f"🤖 Essai {m['nom']}...")
            result = m["fn"](prompt_complet, m["model"])
            log(f"✅ IA OK avec {m['nom']}")
            working_provider = m["nom"]
            modeles_status[m["nom"]] = {"status": "✅ OK", "time": time.strftime("%H:%M:%S")}
            return result
        except Exception as e:
            log(f"❌ {m['nom']} échoué : {e}")
            modeles_status[m["nom"]] = {"status": f"❌ {str(e)[:80]}", "time": time.strftime("%H:%M:%S")}

    log("❌ TOUS LES MODÈLES ONT ÉCHOUÉ")
    return None

def reset_memoire():
    global etat, memoire
    etat = "attente"
    memoire = {
        "niveau": "",
        "sujet": "",
        "questions": [],
        "index": 0,
        "question_actuelle": "",
        "timestamp": 0
    }
    log("🧹 Mémoire effacée")

def est_nouvelle_session(texte):
    if len(texte) < 3:
        return False
    if not texte[0].isdigit():
        return False
    reste = texte[1:].strip()
    return any(c.isalpha() for c in reste)

def verifier_timeout():
    if memoire["timestamp"] > 0:
        elapsed = time.time() - memoire["timestamp"]
        if elapsed > TIMEOUT:
            log(f"⏰ Timeout ({int(elapsed)}s > {TIMEOUT}s)")
            reset_memoire()
            return True
    return False

def envoyer_question_actuelle():
    idx = memoire["index"]
    questions = memoire["questions"]

    if idx >= len(questions):
        log("🎉 Toutes les questions ont été posées !")
        encoded = encode("fin")
        envoyer_scratch(encoded)
        reset_memoire()
        return False

    question = questions[idx].strip()
    memoire["question_actuelle"] = question
    memoire["timestamp"] = time.time()

    log(f"📝 Question {idx+1}/{len(questions)} : '{question}'")

    encoded = encode(question)
    log(f"🔢 Encodée ({len(encoded)} chiffres)")

    ok = envoyer_scratch(encoded)
    if ok:
        log(f"✅ Question {idx+1} confirmée !")
    else:
        log(f"❌ Question {idx+1} : échec total")
    return ok

def traiter_message(val):
    global etat, memoire

    log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log(f"📡 Reçu : {val}")
    log(f"📡 État : {etat}")

    texte = decode(val)
    if not texte:
        log("❌ Décodage vide")
        log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        return False

    log(f"📖 Décodé : '{texte}'")

    if est_nouvelle_session(texte) and etat != "attente":
        log("🔄 Nouvelle session détectée ! Reset...")
        reset_memoire()

    verifier_timeout()

    if etat == "attente":
        if not est_nouvelle_session(texte):
            log(f"⚠️ Ignoré : '{texte}' (pas niveau+sujet)")
            log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            return False

        niveau = texte[0]
        sujet = texte[1:].strip()

        log(f"📚 Niveau : {niveau}ème")
        log(f"📚 Sujet : {sujet}")

        prompt = (
            f"Tu es un professeur. "
            f"Génère exactement 10 questions courtes et variées pour un élève de {niveau}ème "
            f"sur le sujet : {sujet}. "
            f"Écris UNE question par ligne. "
            f"Chaque question doit faire maximum 80 caractères. "
            f"Pas de numérotation. Pas de tiret. Juste la question. "
            f"En français."
        )

        log("🤖 Génération de 10 questions...")
        reponse = demander_ia(prompt)

        if not reponse:
            log("❌ Pas de réponse IA")
            log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            return False

        log(f"🤖 Réponse brute :\n{reponse}")

        lignes = [l.strip() for l in reponse.split('\n') if l.strip() and len(l.strip()) > 5]
        questions_clean = []
        for l in lignes:
            while l and (l[0].isdigit() or l[0] in '.)-:'):
                l = l[1:].strip()
            l_clean = ''.join(c for c in l.lower() if c in CHARS).strip()
            if l_clean and len(l_clean) > 5:
                questions_clean.append(l_clean)

        if len(questions_clean) < 1:
            log("❌ Aucune question valide")
            log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            return False

        questions_clean = questions_clean[:10]
        log(f"✅ {len(questions_clean)} questions :")
        for i, q in enumerate(questions_clean):
            log(f"   {i+1}. {q}")

        memoire["niveau"] = niveau
        memoire["sujet"] = sujet
        memoire["questions"] = questions_clean
        memoire["index"] = 0
        memoire["timestamp"] = time.time()
        etat = "attend_ok"

        envoyer_question_actuelle()
        etat = "attend_reponse"

        log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        return True

    elif etat == "attend_ok":
        if texte.strip() == "ok":
            log("👍 OK reçu !")
            memoire["timestamp"] = time.time()
            ok = envoyer_question_actuelle()
            if ok:
                etat = "attend_reponse"
            log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            return ok
        else:
            log(f"⚠️ Attendait 'ok', reçu '{texte}'")
            if est_nouvelle_session(texte):
                reset_memoire()
                return traiter_message(val)
            log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            return False

    elif etat == "attend_reponse":
        reponse_eleve = texte
        log(f"📝 Réponse : '{reponse_eleve}'")
        log(f"💾 Question : '{memoire['question_actuelle']}'")

        prompt = (
            f"Voici une question posée à un élève de {memoire['niveau']}ème "
            f"sur le sujet {memoire['sujet']} : "
            f"{memoire['question_actuelle']} "
            f"Voici la réponse de l'élève : {reponse_eleve} "
            f"Cette réponse est-elle correcte ? "
            f"Réponds UNIQUEMENT par le mot vrai ou le mot faux, "
            f"rien d'autre, pas de majuscule, pas de ponctuation."
        )

        log("🤖 Vérification...")
        reponse_brute = demander_ia(prompt)

        if not reponse_brute:
            log("❌ Pas de réponse IA")
            reset_memoire()
            log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            return False

        log(f"🤖 Réponse IA : '{reponse_brute}'")

        reponse_lower = reponse_brute.lower().strip()
        if "vrai" in reponse_lower:
            resultat = "vrai"
        elif "faux" in reponse_lower:
            resultat = "faux"
        else:
            resultat = ''.join(c for c in reponse_lower if c in CHARS).strip()[:120]

        log(f"✏️ Résultat : '{resultat}'")

        encoded = encode(resultat)
        ok = envoyer_scratch(encoded)

        if ok:
            log(f"✅ '{resultat}' confirmé reçu par Scratch !")
        else:
            log(f"❌ '{resultat}' NON reçu par Scratch")

        memoire["index"] += 1
        memoire["timestamp"] = time.time()

        if memoire["index"] >= len(memoire["questions"]):
            log("🎉 10/10 terminé !")
            reset_memoire()
        else:
            etat = "attend_ok"
            log(f"⏳ Attente 'ok' pour question {memoire['index']+1}")

        log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        return ok

def boucle_ia():
    global status, last_val
    time.sleep(2)

    for i in range(5):
        if login_scratch():
            break
        log(f"🔄 Tentative login {i+1}/5...")
        time.sleep(10)

    if not session_obj:
        status = "❌ Login impossible"
        return

    for i in range(5):
        if connecter_cloud():
            break
        log(f"🔄 Tentative cloud {i+1}/5...")
        time.sleep(5)

    if not conn:
        status = "❌ Cloud impossible"
        return

    old = lire_variable()
    last_val = old
    log(f"🔄 Valeur initiale ignorée : {old}")
    reset_memoire()

    status = "✅ En ligne"
    log("✅ DevoirGPT v5 prêt !")

    while True:
        try:
            verifier_timeout()
            val = lire_variable()

            if val.startswith("1") and len(val) > 4 and val != last_val:
                last_val = val
                status = f"🤖 {etat} ({memoire['index']+1}/10)"
                try:
                    traiter_message(val)
                except Exception as e:
                    log(f"❌ Erreur traitement : {e}")
                    connecter_cloud()
                status = f"✅ En ligne ({etat})"
            elif val != last_val:
                last_val = val

            time.sleep(3)

        except Exception as e:
            log(f"❌ Erreur boucle : {e}")
            status = "🔄 Reconnexion..."
            time.sleep(5)
            connecter_cloud()
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
    time.sleep(10)
    while True:
        try:
            if RENDER_URL:
                http_requests.get(f"{RENDER_URL}/tick", timeout=10)
        except:
            pass
        time.sleep(25)

def tester_tous_modeles():
    global modeles_status
    log("🧪 Test de tous les modèles...")
    for m in TOUS_LES_MODELES:
        try:
            log(f"🧪 Test {m['nom']}...")
            result = m["fn"]("Dis juste ok", m["model"])
            modeles_status[m["nom"]] = {
                "status": f"✅ → '{result[:30]}'",
                "time": time.strftime("%H:%M:%S")
            }
            log(f"✅ {m['nom']} OK")
        except Exception as e:
            modeles_status[m["nom"]] = {
                "status": f"❌ {str(e)[:80]}",
                "time": time.strftime("%H:%M:%S")
            }
            log(f"❌ {m['nom']} : {e}")

HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>DevoirGPT</title>
<style>
body { font-family: monospace; background: #fff; padding: 20px;
       max-width: 700px; margin: auto; }
h1 { font-size: 18px; margin-bottom: 15px; }
h2 { font-size: 14px; margin: 10px 0 5px; }
#status { font-size: 16px; padding: 10px; border: 2px solid #000;
          margin-bottom: 5px; text-align: center; }
#thread { font-size: 12px; padding: 5px; border: 1px solid #ccc;
          margin-bottom: 5px; text-align: center; color: #666; }
#mem { font-size: 11px; padding: 5px; border: 1px solid #ccc;
       margin-bottom: 10px; color: #336; line-height: 1.5; }
#logs { border: 1px solid #ccc; padding: 8px; height: 400px;
        overflow-y: auto; font-size: 11px; background: #f9f9f9;
        line-height: 1.6; }
.ok { color: green; font-weight: bold; }
.err { color: red; font-weight: bold; }
.step { color: #1565c0; }
.sep { color: #ccc; }
.warn { color: orange; }
.mem { color: purple; }
p { font-size: 11px; color: #888; margin: 8px 0; }
button { padding: 6px 14px; border: 1px solid #000; background: #fff;
         cursor: pointer; font-family: monospace; font-size: 12px; margin: 2px; }
button:hover { background: #ddd; }
#models { border: 1px solid #ccc; padding: 8px; margin-bottom: 10px;
          font-size: 11px; background: #f5f5ff; display: none; }
#models table { width: 100%; border-collapse: collapse; }
#models td { padding: 3px 6px; border-bottom: 1px solid #eee; }
.model_ok { color: green; }
.model_err { color: red; }
</style>
</head>
<body>
<h1>📚 DevoirGPT v5</h1>
<div id="status">...</div>
<div id="thread">...</div>
<div id="mem">...</div>

<div style="margin-bottom:10px">
    <button onclick="toggleModels()">🤖 État des modèles</button>
    <button onclick="testModels()">🧪 Tester tous</button>
</div>

<div id="models">
    <h2>🤖 Modèles IA</h2>
    <div id="models_content">Clique "Tester tous"</div>
</div>

<p>Cerebras → Groq → Gemini | Envoi vérifié 5x | Login unique</p>
<div id="logs"></div>

<script>
function toggleModels() {
    let el = document.getElementById('models');
    el.style.display = el.style.display === 'none' ? 'block' : 'none';
    refreshModels();
}
function testModels() {
    document.getElementById('models').style.display = 'block';
    document.getElementById('models_content').innerHTML = '⏳ Test...';
    fetch('/test_models').then(r=>r.json()).then(d=>{
        refreshModels();
        refreshLogs();
    });
}
function refreshModels() {
    fetch('/api').then(r=>r.json()).then(d=>{
        let ms = d.modeles_status;
        if (!ms || Object.keys(ms).length === 0) {
            document.getElementById('models_content').innerHTML = 'Aucun test';
            return;
        }
        let html = '<table><tr><td><b>Modèle</b></td><td><b>État</b></td><td><b>Heure</b></td></tr>';
        for (let nom in ms) {
            let s = ms[nom];
            let cls = s.status.includes('✅') ? 'model_ok' : 'model_err';
            html += '<tr><td>' + nom + '</td><td class="' + cls + '">' + s.status + '</td><td>' + s.time + '</td></tr>';
        }
        html += '</table>';
        if (d.model) html += '<br><b>Actif : ' + d.model + '</b>';
        document.getElementById('models_content').innerHTML = html;
    });
}
function refreshLogs() {
    fetch('/api').then(r=>r.json()).then(d=>{
        document.getElementById('status').innerText=d.status;
        document.getElementById('thread').innerText=
            'Thread: '+d.thread+' | IA: '+(d.model||'aucun');
        let m=d.memoire;
        document.getElementById('mem').innerHTML=
            'État: <b>'+d.etat+'</b> | Niveau: '+(m.niveau||'-')+
            'ème | Sujet: '+(m.sujet||'-')+
            '<br>Question '+(m.index+1)+'/'+m.questions.length+
            ' : '+(m.question_actuelle||'-');
        let h='';
        d.logs.forEach(l=>{
            let c='';
            if(l.includes('✅')||l.includes('🎉'))c='ok';
            else if(l.includes('❌'))c='err';
            else if(l.includes('📡')||l.includes('📖')||l.includes('📝'))c='step';
            else if(l.includes('━'))c='sep';
            else if(l.includes('⚠')||l.includes('⏰'))c='warn';
            else if(l.includes('💾'))c='mem';
            h+='<div class="'+c+'">'+l+'</div>';
        });
        document.getElementById('logs').innerHTML=h;
        document.getElementById('logs').scrollTop=99999;
    });
}
setInterval(refreshLogs,2000);
refreshLogs();
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
        status=status, logs=logs, thread=t, model=working_provider,
        etat=etat, memoire=memoire, modeles_status=modeles_status
    )

@app.route('/tick')
def tick():
    t = verifier_thread()
    return jsonify(status="ok", thread=t)

@app.route('/test_models')
def test_models_route():
    tester_tous_modeles()
    return jsonify(status="Tests terminés")

ia_thread = threading.Thread(target=boucle_ia, daemon=True)
ia_thread.start()
threading.Thread(target=self_ping, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

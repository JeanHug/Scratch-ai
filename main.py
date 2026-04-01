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

TIMEOUT = 180  # 3 minutes au lieu de 2

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
        url = f"https://clouddata.scratch.mit.edu/logs?projectid={PROJECT_ID}&limit=3&offset=0"
        r = http_requests.get(url, timeout=5)
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
            return False
        conn = session_obj.connect_cloud(PROJECT_ID)
        time.sleep(0.3)
        return True
    except Exception as e:
        log(f"❌ Cloud échoué : {e}")
        conn = None
        return False

def login_et_cloud():
    global session_obj, conn
    try:
        if conn:
            try:
                conn.disconnect()
            except:
                pass
            conn = None
        session_obj = scratch.login(SCRATCH_USER, SCRATCH_PASS)
        conn = session_obj.connect_cloud(PROJECT_ID)
        time.sleep(0.3)
        log("✅ Login + cloud OK !")
        return True
    except Exception as e:
        log(f"❌ Login complet échoué : {e}")
        conn = None
        return False

def envoyer_scratch(valeur):
    global conn
    valeur_str = str(valeur)

    for tentative in range(5):
        try:
            if tentative >= 3:
                login_et_cloud()
            elif tentative > 0 or not conn:
                connecter_cloud()

            if not conn:
                time.sleep(0.5)
                continue

            conn.set_var("Messages sent", valeur_str)

            for verif_try in range(3):
                time.sleep(0.8)
                verif = lire_variable()
                if verif == valeur_str:
                    log(f"✅ Vérifié tentative {tentative+1}")
                    return True

            conn = None

        except Exception as e:
            log(f"❌ Envoi {tentative+1} : {e}")
            conn = None
            time.sleep(0.5)

    log("❌❌❌ ÉCHEC TOTAL 5 tentatives")
    return False

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
    r = http_requests.post(url, headers=headers, json=data, timeout=15)
    if r.status_code != 200:
        raise Exception(f"HTTP {r.status_code}: {r.text[:200]}")
    return r.json()["choices"][0]["message"]["content"].strip()

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
    r = http_requests.post(url, headers=headers, json=data, timeout=15)
    if r.status_code != 200:
        raise Exception(f"HTTP {r.status_code}: {r.text[:200]}")
    return r.json()["choices"][0]["message"]["content"].strip()

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
                    modeles_status[m["nom"]] = {"status": "✅ OK", "time": time.strftime("%H:%M:%S")}
                    return result
                except Exception as e:
                    log(f"⚠️ {m['nom']} : {e}")
                    modeles_status[m["nom"]] = {"status": f"❌ {str(e)[:50]}", "time": time.strftime("%H:%M:%S")}
                    working_provider = None
                break

    for m in TOUS_LES_MODELES:
        try:
            result = m["fn"](prompt_complet, m["model"])
            log(f"✅ IA : {m['nom']}")
            working_provider = m["nom"]
            modeles_status[m["nom"]] = {"status": "✅ OK", "time": time.strftime("%H:%M:%S")}
            return result
        except Exception as e:
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
    return any(c.isalpha() for c in texte[1:])

def verifier_timeout():
    if memoire["timestamp"] > 0:
        elapsed = time.time() - memoire["timestamp"]
        if elapsed > TIMEOUT:
            log(f"⏰ Timeout ({int(elapsed)}s)")
            reset_memoire()
            return True
    return False

def envoyer_question_actuelle():
    idx = memoire["index"]
    questions = memoire["questions"]

    if idx >= len(questions):
        log("🎉 Toutes les questions posées !")
        envoyer_scratch(encode("fin"))
        reset_memoire()
        return False

    question = questions[idx].strip()
    memoire["question_actuelle"] = question
    memoire["timestamp"] = time.time()

    log(f"📝 Q{idx+1}/{len(questions)} : '{question}'")
    return envoyer_scratch(encode(question))

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
        log("🔄 Nouvelle session ! Reset...")
        reset_memoire()

    verifier_timeout()

    if etat == "attente":
        if not est_nouvelle_session(texte):
            log(f"⚠️ Ignoré : '{texte}'")
            log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            return False

        niveau = texte[0]
        sujet = texte[1:].strip()
        log(f"📚 {niveau}ème — {sujet}")

        prompt = (
            f"Tu es un professeur. "
            f"Génère exactement 10 questions courtes et variées pour un élève de {niveau}ème "
            f"sur le sujet : {sujet}. "
            f"Écris UNE question par ligne. "
            f"Chaque question doit faire maximum 80 caractères. "
            f"Pas de numérotation. Pas de tiret. Juste la question. "
            f"En français."
        )

        log("🤖 Génération...")
        reponse = demander_ia(prompt)

        if not reponse:
            log("❌ Pas de réponse IA")
            log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            return False

        lignes = [l.strip() for l in reponse.split('\n') if l.strip() and len(l.strip()) > 5]
        questions_clean = []
        for l in lignes:
            while l and (l[0].isdigit() or l[0] in '.)-:'):
                l = l[1:].strip()
            l_clean = ''.join(c for c in l.lower() if c in CHARS).strip()
            if l_clean and len(l_clean) > 5:
                questions_clean.append(l_clean)

        if not questions_clean:
            log("❌ Aucune question valide")
            log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            return False

        questions_clean = questions_clean[:10]
        log(f"✅ {len(questions_clean)} questions")
        for i, q in enumerate(questions_clean):
            log(f"   {i+1}. {q}")

        memoire["niveau"] = niveau
        memoire["sujet"] = sujet
        memoire["questions"] = questions_clean
        memoire["index"] = 0
        memoire["timestamp"] = time.time()

        envoyer_question_actuelle()
        etat = "attend_reponse"
        log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        return True

    elif etat == "attend_ok":
        if texte.strip() == "ok":
            log("👍 OK !")
            memoire["timestamp"] = time.time()
            ok = envoyer_question_actuelle()
            if ok:
                etat = "attend_reponse"
            log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            return ok
        else:
            if est_nouvelle_session(texte):
                reset_memoire()
                return traiter_message(val)
            log(f"⚠️ Attendait 'ok', reçu '{texte}'")
            log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            return False

    elif etat == "attend_reponse":
        reponse_eleve = texte
        log(f"📝 Réponse : '{reponse_eleve}'")
        log(f"💾 Q : '{memoire['question_actuelle']}'")

        # Mettre à jour le timestamp MAINTENANT pour éviter le timeout pendant que l'IA réfléchit
        memoire["timestamp"] = time.time()

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

        reponse_lower = reponse_brute.lower().strip()
        if "vrai" in reponse_lower:
            resultat = "vrai"
        elif "faux" in reponse_lower:
            resultat = "faux"
        else:
            resultat = ''.join(c for c in reponse_lower if c in CHARS).strip()[:120]

        log(f"✏️ → {resultat}")

        # Mettre à jour le timestamp ENCORE pour éviter timeout pendant l'envoi
        memoire["timestamp"] = time.time()

        ok = envoyer_scratch(encode(resultat))

        if ok:
            log(f"✅ '{resultat}' confirmé !")
        else:
            log(f"❌ '{resultat}' non reçu")

        memoire["index"] += 1
        memoire["timestamp"] = time.time()

        if memoire["index"] >= len(memoire["questions"]):
            log("🎉 10/10 !")
            reset_memoire()
        else:
            etat = "attend_ok"
            log(f"⏳ Attente ok → Q{memoire['index']+1}")

        log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        return ok

def boucle_ia():
    global status, last_val
    time.sleep(1)

    for i in range(5):
        if login_scratch():
            break
        time.sleep(5)

    if not session_obj:
        status = "❌ Login impossible"
        return

    for i in range(5):
        if connecter_cloud():
            break
        time.sleep(3)

    if not conn:
        status = "❌ Cloud impossible"
        return

    old = lire_variable()
    last_val = old
    log(f"🔄 Ignoré : {old}")
    reset_memoire()

    status = "✅ En ligne"
    log("✅ DevoirGPT v6 prêt !")

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
                    log(f"❌ Erreur : {e}")
                    connecter_cloud()
                status = f"✅ En ligne ({etat})"
            elif val != last_val:
                last_val = val

            time.sleep(1)

        except Exception as e:
            log(f"❌ Erreur boucle : {e}")
            time.sleep(3)
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
                http_requests.get(f"{RENDER_URL}/tick", timeout=5)
        except:
            pass
        time.sleep(20)

def tester_tous_modeles():
    global modeles_status
    log("🧪 Test modèles...")
    for m in TOUS_LES_MODELES:
        try:
            result = m["fn"]("Dis ok", m["model"])
            modeles_status[m["nom"]] = {"status": f"✅ '{result[:20]}'", "time": time.strftime("%H:%M:%S")}
        except Exception as e:
            modeles_status[m["nom"]] = {"status": f"❌ {str(e)[:80]}", "time": time.strftime("%H:%M:%S")}

HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>DevoirGPT</title>
<style>
body{font-family:monospace;background:#fff;padding:20px;max-width:700px;margin:auto}
h1{font-size:18px;margin-bottom:15px}
h2{font-size:14px;margin:10px 0 5px}
#status{font-size:16px;padding:10px;border:2px solid #000;margin-bottom:5px;text-align:center}
#thread{font-size:12px;padding:5px;border:1px solid #ccc;margin-bottom:5px;text-align:center;color:#666}
#mem{font-size:11px;padding:5px;border:1px solid #ccc;margin-bottom:10px;color:#336;line-height:1.5}
#logs{border:1px solid #ccc;padding:8px;height:400px;overflow-y:auto;font-size:11px;background:#f9f9f9;line-height:1.6}
.ok{color:green;font-weight:bold}.err{color:red;font-weight:bold}.step{color:#1565c0}
.sep{color:#ccc}.warn{color:orange}.mem{color:purple}
p{font-size:11px;color:#888;margin:8px 0}
button{padding:6px 14px;border:1px solid #000;background:#fff;cursor:pointer;font-family:monospace;font-size:12px;margin:2px}
button:hover{background:#ddd}
#models{border:1px solid #ccc;padding:8px;margin-bottom:10px;font-size:11px;background:#f5f5ff;display:none}
#models table{width:100%;border-collapse:collapse}
#models td{padding:3px 6px;border-bottom:1px solid #eee}
.model_ok{color:green}.model_err{color:red}
</style>
</head>
<body>
<h1>📚 DevoirGPT v6</h1>
<div id="status">...</div>
<div id="thread">...</div>
<div id="mem">...</div>
<div style="margin-bottom:10px">
<button onclick="toggleModels()">🤖 Modèles</button>
<button onclick="testModels()">🧪 Tester</button>
</div>
<div id="models"><h2>🤖 Modèles</h2><div id="mc">Clique Tester</div></div>
<p>Cerebras→Groq→Gemini | Vérifié 5x | Polling 1s</p>
<div id="logs"></div>
<script>
function toggleModels(){let e=document.getElementById('models');e.style.display=e.style.display==='none'?'block':'none';rm()}
function testModels(){document.getElementById('models').style.display='block';document.getElementById('mc').innerHTML='⏳...';fetch('/test_models').then(r=>r.json()).then(d=>{rm();rl()})}
function rm(){fetch('/api').then(r=>r.json()).then(d=>{let ms=d.modeles_status;if(!ms||!Object.keys(ms).length){document.getElementById('mc').innerHTML='Aucun test';return}let h='<table><tr><td><b>Modèle</b></td><td><b>État</b></td></tr>';for(let n in ms){let s=ms[n];h+='<tr><td>'+n+'</td><td class="'+(s.status.includes('✅')?'model_ok':'model_err')+'">'+s.status+'</td></tr>'}h+='</table>';if(d.model)h+='<br><b>Actif: '+d.model+'</b>';document.getElementById('mc').innerHTML=h})}
function rl(){fetch('/api').then(r=>r.json()).then(d=>{document.getElementById('status').innerText=d.status;document.getElementById('thread').innerText='Thread: '+d.thread+' | IA: '+(d.model||'-');let m=d.memoire;document.getElementById('mem').innerHTML='État: <b>'+d.etat+'</b> | '+((m.niveau||'-'))+'ème '+(m.sujet||'-')+'<br>Q'+(m.index+1)+'/'+m.questions.length+': '+(m.question_actuelle||'-');let h='';d.logs.forEach(l=>{let c='';if(l.includes('✅')||l.includes('🎉'))c='ok';else if(l.includes('❌'))c='err';else if(l.includes('📡')||l.includes('📖')||l.includes('📝'))c='step';else if(l.includes('━'))c='sep';else if(l.includes('⚠')||l.includes('⏰'))c='warn';else if(l.includes('💾'))c='mem';h+='<div class="'+c+'">'+l+'</div>'});document.getElementById('logs').innerHTML=h;document.getElementById('logs').scrollTop=99999})}
setInterval(rl,2000);rl()
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
    return jsonify(status=status,logs=logs,thread=t,model=working_provider,etat=etat,memoire=memoire,modeles_status=modeles_status)

@app.route('/tick')
def tick():
    t = verifier_thread()
    return jsonify(status="ok",thread=t)

@app.route('/test_models')
def test_models_route():
    tester_tous_modeles()
    return jsonify(status="OK")

ia_thread = threading.Thread(target=boucle_ia, daemon=True)
ia_thread.start()
threading.Thread(target=self_ping, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

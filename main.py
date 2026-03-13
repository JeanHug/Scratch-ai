import os
import time
import threading
from flask import Flask
import scratchattach as scratch
import google.generativeai as genai

app = Flask(__name__)

@app.route('/')
def home():
    return "Robot en ligne !"

# ── IA ──
genai.configure(api_key=os.getenv("GEMINI_KEY"))
model = genai.GenerativeModel('gemini-3-flash-preview')

CHARS = " abcdefghijklmnopqrstuvwxyz0123456789.,!?@'\"()+-*/=:_éàè"

def decode(encoded_str):
    data = str(encoded_str)[1:]
    text = ""
    for i in range(0, len(data), 2):
        idx = int(data[i:i+2])
        if 1 <= idx <= len(CHARS):
            text += CHARS[idx - 1]
    return text

def encode(text):
    result = "2"
    for c in text.lower():
        if c in CHARS:
            result += str(CHARS.index(c) + 1).zfill(2)
    return result

# ── Connexion Scratch ──
project_id = os.getenv("SCRATCH_ID")
print("🔌 Connexion...", flush=True)

try:
    session = scratch.login(os.getenv("SCRATCH_USER"), os.getenv("SCRATCH_PASS"))
    conn = session.connect_cloud(project_id)       # pour ÉCRIRE
    print("✅ Connecté !", flush=True)
except Exception as e:
    print(f"❌ CONNEXION ÉCHOUÉE : {e}", flush=True)
    conn = None

# ── Fonction pour LIRE (séparée de conn) ──
def lire_variable():
    """Lit via l'API REST, pas via le websocket"""
    logs = scratch.get_cloud(project_id)
    valeurs = logs.get_var("Messages sent")
    return str(valeurs).split(".")[0] if valeurs else "0"

# ── Boucle ──
def boucle():
    if not conn:
        print("❌ Pas de connexion.", flush=True)
        return

    print("🔄 Boucle démarrée !", flush=True)
    last = ""

    while True:
        try:
            val = lire_variable()
            print(f"🔍 Lu : {val}", flush=True)

            if val.startswith("1") and val != last and val != "0":
                last = val
                question = decode(val)
                print(f"📩 Question : {question}", flush=True)

                res = model.generate_content(
                    "Réponds en français, très court, max 30 caractères, "
                    "pas d'émoji, pas de markdown : " + question
                )
                reponse = ''.join(
                    c for c in res.text.strip().lower() if c in CHARS
                )[:40]
                print(f"🤖 Réponse : {reponse}", flush=True)

                encoded = encode(reponse)
                conn.set_var("Messages sent", encoded)
                print(f"📤 Envoyé : {encoded}", flush=True)

            time.sleep(2)

        except Exception as e:
            print(f"❌ Erreur : {e}", flush=True)
            time.sleep(5)

thread = threading.Thread(target=boucle, daemon=True)
thread.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

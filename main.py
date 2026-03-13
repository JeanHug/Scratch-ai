import os
import time
import threading
from flask import Flask
import scratchattach as scratch
import google.generativeai as genai

app = Flask(__name__)

@app.route('/')
def home():
    return "Le robot est en ligne !"

# ── Configuration IA ──
genai.configure(api_key=os.getenv("GEMINI_KEY"))
model = genai.GenerativeModel('gemini-3-flash-preview')

# Table de caractères (index 1 à 56, doit correspondre à la liste Scratch)
CHARS = " abcdefghijklmnopqrstuvwxyz0123456789.,!?@'\"()+-*/=:_éàè"

# ── Encodage / Décodage ──

def decode_from_scratch(encoded_str):
    """'11902122120' → 'salut'"""
    data = str(encoded_str)[1:]  # retirer le préfixe "1"
    text = ""
    for i in range(0, len(data), 2):
        idx = int(data[i:i+2])
        if 1 <= idx <= len(CHARS):
            text += CHARS[idx - 1]
    return text

def encode_for_scratch(text):
    """'bonjour' → '2031516101721'"""
    encoded = "2"
    for char in text.lower():
        if char in CHARS:
            idx = CHARS.index(char) + 1
            encoded += str(idx).zfill(2)  # 5 → "05"
    return encoded

# ── Connexion Scratch ──
print("🔌 Connexion à Scratch...")
try:
    session = scratch.login(os.getenv("SCRATCH_USER"), os.getenv("SCRATCH_PASS"))
    conn = session.connect_cloud(os.getenv("SCRATCH_ID"))
    print("✅ Connecté !")
except Exception as e:
    print(f"❌ Connexion échouée : {e}")
    conn = None

# ── Boucle principale ──

def boucle_scratch():
    if conn is None:
        print("❌ Pas de connexion cloud.")
        return

    last_val = "0"
    while True:
        try:
            raw = conn.get_var("message")
            valeur = str(raw).split(".")[0]

            if valeur != "0" and valeur != last_val and valeur.startswith("1"):
                last_val = valeur

                # 1) Décoder
                question = decode_from_scratch(valeur)
                print(f"📩 Question : {question}")

                # 2) IA
                res = model.generate_content(
                    "Réponds en français, très court (max 30 caractères, "
                    "pas d'émoji, pas de markdown) : " + question
                )
                reponse = res.text.strip()
                reponse = ''.join(c for c in reponse.lower() if c in CHARS)[:40]
                print(f"🤖 Réponse : {reponse}")

                # 3) Encoder et envoyer sur "Messages sent"
                encoded = encode_for_scratch(reponse)
                conn.set_var("Messages sent", encoded)
                print(f"📤 Envoyé : {encoded}")

                # 4) Remettre message à 0
                conn.set_var("message", "0")

            time.sleep(2)

        except Exception as e:
            print(f"❌ Erreur : {e}")
            time.sleep(5)

# Lancer HORS du if __name__ (pour gunicorn)
thread = threading.Thread(target=boucle_scratch, daemon=True)
thread.start()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=10000)

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
model = genai.GenerativeModel('gemini-2.0-flash')  # Vérifie le nom du modèle

# Table de caractères (DOIT correspondre à la liste Scratch, index 1 à 56)
CHARS = " abcdefghijklmnopqrstuvwxyz0123456789.,!?@'\"()+-*/=:_éàè"

# ── Fonctions d'encodage/décodage ──

def decode_from_scratch(encoded_str):
    """'10506' → 'de'  (retire le préfixe '1', lit par paires)"""
    data = str(encoded_str)[1:]          # retirer le "1"
    text = ""
    for i in range(0, len(data), 2):
        idx = int(data[i:i+2])
        if 1 <= idx <= len(CHARS):
            text += CHARS[idx - 1]       # -1 car Python est 0-indexé
    return text

def encode_for_scratch(text):
    """'de' → '20506'  (ajoute le préfixe '2', chaque char = 2 chiffres)"""
    encoded = "2"
    for char in text.lower():
        if char in CHARS:
            idx = CHARS.index(char) + 1  # +1 car Scratch est 1-indexé
            encoded += str(idx).zfill(2)  # zéro-padding : 5 → "05"
    return encoded

# ── Connexion Scratch ──
print("🔌 Connexion à Scratch...")
try:
    session = scratch.login(os.getenv("SCRATCH_USER"), os.getenv("SCRATCH_PASS"))
    # Alternative si le login par mot de passe ne marche plus :
    # session = scratch.Session(os.getenv("SCRATCH_SESSION"), username=os.getenv("SCRATCH_USER"))
    conn = session.connect_cloud(os.getenv("SCRATCH_ID"))
    print("✅ Connecté à Scratch !")
except Exception as e:
    print(f"❌ Connexion Scratch échouée : {e}")
    conn = None

# ── Boucle principale ──

def boucle_scratch():
    if conn is None:
        print("❌ Pas de connexion, boucle arrêtée.")
        return

    last_val = "0"
    while True:
        try:
            raw = conn.get_var("message")
            valeur = str(raw).split(".")[0]   # "0.0" → "0"

            if valeur != "0" and valeur != last_val and valeur.startswith("1"):
                last_val = valeur

                # 1) DÉCODER le message Scratch
                question = decode_from_scratch(valeur)
                print(f"📩 Question : {question}")

                # 2) Demander à l'IA
                res = model.generate_content(
                    "Réponds en français, très court (max 30 caractères, "
                    "pas d'émoji, pas de markdown) : " + question
                )
                reponse = res.text.strip()

                # 3) Nettoyer (garder uniquement les caractères supportés)
                reponse = ''.join(c for c in reponse.lower() if c in CHARS)[:40]
                print(f"🤖 Réponse : {reponse}")

                # 4) ENCODER et envoyer sur la MÊME variable
                encoded = encode_for_scratch(reponse)
                conn.set_var("message", encoded)
                print(f"📤 Envoyé : {encoded}")

            time.sleep(2)

        except Exception as e:
            print(f"❌ Erreur boucle : {e}")
            time.sleep(5)

# ── Lancement (HORS du if __name__) ──
thread = threading.Thread(target=boucle_scratch, daemon=True)
thread.start()
print("🚀 Thread Scratch démarré !")

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=10000)

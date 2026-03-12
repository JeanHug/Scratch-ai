import os
import time
from flask import Flask
import scratchattach as scratch
import google.generativeai as genai

# Configuration
app = Flask(__name__)
@app.route('/')
def home():
    return "Le robot est en ligne !"

# Connexion IA
genai.configure(api_key=os.getenv("GEMINI_KEY"))
model = genai.GenerativeModel('gemini-3-flash-preview')
CHARS = " abcdefghijklmnopqrstuvwxyz0123456789.,!?@'\"()+-*/=:_éàè"

# Connexion Scratch
print("Connexion à Scratch...")
session = scratch.login(os.getenv("SCRATCH_USER"), os.getenv("SCRATCH_PASS"))
conn = session.connect_cloud(os.getenv("SCRATCH_ID"))
print("🚀 Serveur actif !")

# Lancement serveur Flask et Boucle
if __name__ == "__main__":
    # On lance Flask en mode "non-bloquant" n'est pas possible simplement, 
    # alors on lance la boucle Scratch dans un thread ici.
    import threading
    def boucle_scratch():
        last_val = "0"
        while True:
            try:
                valeur = conn.get_var("message")
                if valeur != "0" and valeur != last_val and str(valeur).startswith("1"):
                    print(f"📩 Reçu : {valeur}")
                    conn.set_var("message", "0")
                    # Traitement IA simplifié
                    res = model.generate_content("Réponds court: " + valeur)
                    conn.set_var("message", "2" + res.text[:50])
                    print("📤 Envoyé.")
                time.sleep(2)
            except Exception as e:
                print(f"Erreur Scratch: {e}")
                time.sleep(5)

    threading.Thread(target=boucle_scratch, daemon=True).start()
    app.run(host='0.0.0.0', port=10000)

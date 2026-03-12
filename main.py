import os
import time
import threading
from flask import Flask
import scratchattach as scratch
import google.generativeai as genai

# --- CONFIGURATION (Tes variables d'environnement sur Render) ---
USERNAME = os.getenv("SCRATCH_USER")
PASSWORD = os.getenv("SCRATCH_PASS")
PROJECT_ID = os.getenv("SCRATCH_ID")
API_KEY = os.getenv("GEMINI_KEY")
CLOUD_VAR_NAME = "message"  # Vérifie bien que ta variable sur Scratch s'appelle comme ça

# --- 1. CONFIGURATION FLASK (Pour rester en ligne sur Render) ---
app = Flask(__name__)
@app.route('/')
def home():
    return "Le robot est en ligne !"

def run_flask():
    app.run(host='0.0.0.0', port=10000)

# Lancement du serveur web en arrière-plan
flask_thread = threading.Thread(target=run_flask)
flask_thread.start()

# --- 2. CONFIGURATION IA ET SCRATCH ---
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')
CHARS = " abcdefghijklmnopqrstuvwxyz0123456789.,!?@'\"()+-*/=:_éàè"

def encode(text):
    return "".join([str(CHARS.index(c)).zfill(2) for c in str(text).lower() if c in CHARS])

def decode(number_str):
    text = ""
    for i in range(0, len(str(number_str)), 2):
        pair = str(number_str)[i:i+2]
        if pair.isdigit() and int(pair) < len(CHARS):
            text += CHARS[int(pair)]
    return text

# --- 3. CONNEXION SCRATCH ---
print("Connexion à Scratch en cours...")
session = scratch.login(USERNAME, PASSWORD)
conn = session.connect_cloud(PROJECT_ID)
print("🚀 Serveur actif. En attente de message...")

# --- 4. BOUCLE PRINCIPALE ---
last_val = "0"
while True:
    try:
        valeur = conn.get_var(CLOUD_VAR_NAME)
        # Si la valeur change et commence par '1' (code d'envoi de l'utilisateur)
        if valeur != "0" and valeur != last_val:
            if str(valeur).startswith("1"):
                question = decode(str(valeur)[1:])
                print(f"📩 Question reçue : {question}")
                
                # Réinitialisation immédiate
                conn.set_var(CLOUD_VAR_NAME, "0")
                
                # Appel IA
                response = model.generate_content(question)
                reponse_ia = response.text.replace("\n", " ")[:100]
                
                # Envoi réponse (code '2' + texte encodé)
                conn.set_var(CLOUD_VAR_NAME, "2" + encode(reponse_ia))
                print("📤 Réponse envoyée.")
                
            last_val = "0"
        
        time.sleep(1)
    except Exception as e:
        print(f"Erreur dans la boucle : {e}")
        time.sleep(5)

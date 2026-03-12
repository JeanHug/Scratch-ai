from flask import Flask
from threading import Thread
import os

# --- PARTIE POUR GARDER LE SCRIPT EN VIE ---
app = Flask(__name__)
@app.route('/')
def home():
    return "Le robot est en ligne !"

def run():
    app.run(host='0.0.0.0', port=10000)

t = Thread(target=run)
t.start()
# ---------------------------------------------

# ... (le reste de ton code avec le scratch.login et la boucle while)import os
import time
import scratchattach as scratch
import google.generativeai as genai

# --- CONFIGURATION ---
USERNAME = os.getenv("SCRATCH_USER")
PASSWORD = os.getenv("SCRATCH_PASS")
PROJECT_ID = os.getenv("SCRATCH_ID")
API_KEY = os.getenv("GEMINI_KEY")
CLOUD_VAR_NAME = "message" 

genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-3-flash-preview')
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

# --- CONNEXION ---
session = scratch.login(USERNAME, PASSWORD)
conn = session.connect_cloud(PROJECT_ID)

print("🚀 Serveur actif. En attente de message...")

# Boucle pour écouter les changements de la variable Cloud
last_val = "0"
while True:
    try:
        valeur = conn.get_var(CLOUD_VAR_NAME)
        if valeur != "0" and valeur != last_val:
            if str(valeur).startswith("1"):
                question = decode(str(valeur)[1:])
                print(f"📩 Question : {question}")
                
                # Effacer pour traiter
                conn.set_var(CLOUD_VAR_NAME, "0")
                
                # IA
                response = model.generate_content(question)
                reponse_ia = response.text.replace("\n", " ")[:100]
                
                # Envoi
                conn.set_var(CLOUD_VAR_NAME, "2" + encode(reponse_ia))
                print("📤 Réponse envoyée.")
                last_val = "0"
        
        time.sleep(1)
    except Exception as e:
        print(f"Erreur : {e}")
        time.sleep(5)

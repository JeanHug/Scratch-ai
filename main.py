import os
import time
import scratchattach as scratch
import google.generativeai as genai

# --- CONFIGURATION (Variables d'environnement sur Render) ---
USERNAME = os.getenv("SCRATCH_USER")
PASSWORD = os.getenv("SCRATCH_PASS")
PROJECT_ID = os.getenv("SCRATCH_ID")
API_KEY = os.getenv("GEMINI_KEY")

# NOM DE TA VARIABLE (Ex: "Messages sent" si ta variable est ☁ message)
CLOUD_VAR_NAME = "message" 

# --- CONFIGURATION GEMINI ---
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-3-flash-preview')

# --- TABLE DE CARACTÈRES (Strictement identique à Scratch) ---
CHARS = " abcdefghijklmnopqrstuvwxyz0123456789.,!?@'\"()+-*/=:_éàè"

def encode(text):
    encoded = ""
    for char in str(text).lower():
        if char in CHARS:
            index = CHARS.index(char)
            encoded += str(index).zfill(2)
    return encoded

def decode(number_str):
    text = ""
    number_str = str(number_str)
    for i in range(0, len(number_str), 2):
        pair = number_str[i:i+2]
        if pair.isdigit():
            idx = int(pair)
            if idx < len(CHARS):
                text += CHARS[idx]
    return text

# --- CONNEXION ---
try:
    session = scratch.login(USERNAME, PASSWORD)
    conn = session.connect_cloud(PROJECT_ID)
    client = scratch.CloudEvents(PROJECT_ID)
    print(f"🚀 Serveur Talkie-Walkie actif sur la variable : {CLOUD_VAR_NAME}")
except Exception as e:
    print(f"❌ Erreur connexion : {e}")

@client.event
def on_set(event):
    # On ne réagit que si la variable change et n'est pas "0"
    if event.var == CLOUD_VAR_NAME and event.value != "0":
        
        # SÉCURITÉ : On vérifie si le premier chiffre est "1" (Question)
        # On va dire que Scratch envoie des questions commençant par "1"
        # et le Python répond par des messages commençant par "2"
        raw_val = str(event.value)
        
        if raw_val.startswith("1"):
            # C'est une question ! On retire le "1" du début pour décoder
            question_codee = raw_val[1:]
            question_texte = decode(question_codee)
            
            print(f"📩 Question reçue : {question_texte}")

            try:
                # 1. On vide la variable pour dire "Je traite"
                conn.set_var(CLOUD_VAR_NAME, "0")
                
                # 2. Appel Gemini
                response = model.generate_content(question_texte)
                reponse_ia = response.text.replace("\n", " ")[:100] # Max 100 car.
                
                print(f"🤖 Réponse Gemini : {reponse_ia}")

                # 3. On encode et on ajoute "2" au début (Marqueur de réponse)
                reponse_prete = "2" + encode(reponse_ia)
                
                # 4. Envoi
                time.sleep(1) # Petite pause pour la stabilité du cloud
                conn.set_var(CLOUD_VAR_NAME, reponse_prete)
                print("📤 Réponse envoyée avec succès.")

            except Exception as e:
                print(f"⚠️ Erreur IA : {e}")
                conn.set_var(CLOUD_VAR_NAME, "2" + encode("erreur de l ia"))

# Lancement
client.start()

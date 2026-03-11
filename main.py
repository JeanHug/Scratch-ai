import os
import time
import scratchattach as scratch
import google.generativeai as genai

# --- RÉCUPÉRATION DES SECRETS (Variables d'environnement) ---
# Sur Render, tu devras créer ces 4 variables dans l'onglet 'Environment'
USERNAME = os.getenv("SCRATCH_USER")
PASSWORD = os.getenv("SCRATCH_PASS")
PROJECT_ID = os.getenv("SCRATCH_ID")
API_KEY = os.getenv("GEMINI_KEY")

# --- CONFIGURATION GEMINI ---
genai.configure(api_key=API_KEY)
# On utilise le modèle exact que tu as demandé
model = genai.GenerativeModel('gemini-3-flash-preview')

# --- CONFIGURATION SCRATCH ---
# Cette liste doit être la même dans ton projet Scratch (index 1 = espace)
CHARS = " abcdefghijklmnopqrstuvwxyz0123456789.,!?@'\"()+-*/=:_éàè"

def decode_scratch(number_str):
    """Transforme les chiffres de Scratch en texte pour l'IA"""
    text = ""
    number_str = str(number_str)
    for i in range(0, len(number_str), 2):
        pair = number_str[i:i+2]
        if pair.isdigit():
            index = int(pair)
            if index < len(CHARS):
                text += CHARS[index]
    return text

def encode_scratch(text):
    """Transforme la réponse de l'IA en chiffres pour Scratch"""
    encoded = ""
    for char in str(text).lower():
        if char in CHARS:
            index = CHARS.index(char)
            # zfill(2) transforme '5' en '05'
            encoded += str(index).zfill(2)
    return encoded

# --- CONNEXION ---
try:
    print("⏳ Connexion à Scratch...")
    session = scratch.login(USERNAME, PASSWORD)
    conn = session.connect_cloud(PROJECT_ID)
    client = scratch.CloudEvents(PROJECT_ID)
    print(f"✅ Serveur prêt sur le projet {PROJECT_ID} !")
except Exception as e:
    print(f"❌ Erreur de connexion initiale : {e}")

@client.event
def on_set(event):
    # Si la variable 'prompt' change et n'est pas '00' (notre code de reset)
    if event.var == "prompt" and event.value != "00":
        raw_value = event.value
        question = decode_scratch(raw_value)
        
        if not question.strip():
            return

        print(f"📩 Question reçue : {question}")

        try:
            # 1. On "reset" le prompt sur Scratch pour dire qu'on travaille
            conn.set_var("prompt", "00")

            # 2. On demande à Gemini
            response = model.generate_content(question)
            reponse_ia = response.text.replace("\n", " ") # Pas de saut de ligne
            
            # 3. On coupe à 120 caractères (limite des 256 chiffres du Cloud)
            reponse_finale = reponse_ia[:120]
            
            print(f"🤖 Réponse Gemini : {reponse_finale}")

            # 4. On envoie la réponse encodée sur la variable 'reponse'
            conn.set_var("reponse", encode_scratch(reponse_finale))
            print("📤 Réponse envoyée au Cloud.")

        except Exception as e:
            print(f"⚠️ Erreur durant le traitement : {e}")
            conn.set_var("reponse", encode_scratch("erreur technique"))

# Lancement du script
client.start()

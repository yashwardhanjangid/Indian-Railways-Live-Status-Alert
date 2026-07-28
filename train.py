import os
import requests

# GitHub Secrets
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Train Number
TRAIN_NUMBER = "12345"   # <-- Isko baad me apni train number se replace karna

url = f"https://real-time-pnr-status-api-for-indian-railways.p.rapidapi.com/train/{TRAIN_NUMBER}"

headers = {
    "x-rapidapi-key": RAPIDAPI_KEY,
    "x-rapidapi-host": "real-time-pnr-status-api-for-indian-railways.p.rapidapi.com"
}

response = requests.get(url, headers=headers)

print(response.status_code)
print(response.text)

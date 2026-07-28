import os
import requests

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")

TRAIN_NUMBER = "12956"   # <-- Apni train number yahan likh

url = f"https://irctc-api5.p.rapidapi.com/live-status/{TRAIN_NUMBER}"

headers = {
    "Content-Type": "application/json",
    "x-rapidapi-key": RAPIDAPI_KEY,
    "x-rapidapi-host": "irctc-api5.p.rapidapi.com"
}

response = requests.get(url, headers=headers)

print("Status Code:", response.status_code)
print(response.text)

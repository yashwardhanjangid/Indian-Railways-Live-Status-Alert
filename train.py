import os
import json
import requests

API_KEY = os.getenv("RAILRADAR_API_KEY")

TRAIN_NUMBER = "12956"

url = f"https://api.railradar.in/v1/trains/{TRAIN_NUMBER}/live"

headers = {
    "Authorization": f"Bearer {API_KEY}"
}

response = requests.get(url, headers=headers)

print("Status Code:", response.status_code)
with open("response.json", "w") as f:
    json.dump(response.json(), f, indent=2)

print(open("response.json").read())

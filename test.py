# save as test_scope.py
import requests, json
data = json.load(open("client_secrets.json"))
secrets = data.get("installed") or data.get("web")

resp = requests.post(
    "https://oauth2.googleapis.com/device/code",
    data={
        "client_id": secrets["client_id"],
        "scope": "https://www.googleapis.com/auth/youtube https://www.googleapis.com/auth/youtube.force-ssl",
    },
    timeout=20,
)
print("Status:", resp.status_code)
print("Response:", json.dumps(resp.json(), indent=2))
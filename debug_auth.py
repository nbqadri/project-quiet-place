# debug_auth.py
import json
import requests
from dotenv import load_dotenv
load_dotenv()

from config import YOUTUBE_SCOPES   # ← pull from config, not hardcoded

data    = json.load(open("client_secrets.json"))
secrets = data.get("installed") or data.get("web")

print("Scopes being used:", YOUTUBE_SCOPES)

resp = requests.post(
    "https://oauth2.googleapis.com/device/code",
    data={
        "client_id": secrets["client_id"],
        "scope":     " ".join(YOUTUBE_SCOPES),
    },
    timeout=20,
)

print("Status code :", resp.status_code)
print("Response    :", json.dumps(resp.json(), indent=2))
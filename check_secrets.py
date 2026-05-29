# Save as check_secrets.py and run it
import json
data = json.load(open("client_secrets.json"))
print("Top-level keys:", list(data.keys()))
inner = data.get("installed") or data.get("web") or {}
print("Client ID:", inner.get("client_id", "NOT FOUND"))
print("Type detected:", "installed" if "installed" in data else "web" if "web" in data else "UNKNOWN")
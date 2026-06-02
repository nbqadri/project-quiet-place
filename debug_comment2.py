"""
debug_comment2.py - Deep diagnostic for YouTube comment 403 issues.
Run with: python debug_comment2.py
"""
import json
import requests
from dotenv import load_dotenv
load_dotenv()

VIDEO_ID = "TQGRe1QeFYw"   # your public video

# ── 1. Load token ─────────────────────────────────────────────────────────────
try:
    token_data = json.loads(open("youtube_token.json").read())
    token = token_data["access_token"]
    print("✓ Token loaded")
except Exception as e:
    print(f"✗ Could not load token: {e}")
    exit(1)

headers = {"Authorization": f"Bearer {token}"}

# ── 2. Check what scopes the token actually has ────────────────────────────────
print("\n--- Token Info ---")
resp = requests.get(
    f"https://oauth2.googleapis.com/tokeninfo?access_token={token}"
)
info = resp.json()
print(f"Scopes granted : {info.get('scope', 'NOT FOUND')}")
print(f"Expires in     : {info.get('expires_in', 'N/A')} seconds")
print(f"Email          : {info.get('email', 'N/A')}")

granted_scopes = info.get("scope", "")
if "youtube" not in granted_scopes:
    print("\n✗ PROBLEM: Token has no YouTube scopes at all!")
elif "youtube.force-ssl" not in granted_scopes and "//youtube " not in granted_scopes + " ":
    print("\n⚠ WARNING: Token may be missing comment scope")
else:
    print("\n✓ Token appears to have YouTube scope")

# ── 3. Check video details ─────────────────────────────────────────────────────
print(f"\n--- Video Status: {VIDEO_ID} ---")
resp = requests.get(
    "https://www.googleapis.com/youtube/v3/videos",
    headers=headers,
    params={"part": "status,snippet", "id": VIDEO_ID},
)
data = resp.json()
if data.get("items"):
    item = data["items"][0]
    print(f"Title          : {item['snippet']['title']}")
    print(f"Privacy        : {item['status']['privacyStatus']}")
    print(f"Made for kids  : {item['status'].get('madeForKids', 'N/A')}")
    print(f"Comments status: {item['status'].get('publicStatsViewable', 'N/A')}")
    if item['status'].get('madeForKids'):
        print("\n✗ PROBLEM: Video is marked 'Made for Kids' — YouTube DISABLES comments on all such videos by law (COPPA). This cannot be overridden via API.")
else:
    print("Could not fetch video details")

# ── 4. Check channel settings ─────────────────────────────────────────────────
print("\n--- Channel Settings ---")
resp = requests.get(
    "https://www.googleapis.com/youtube/v3/channels",
    headers=headers,
    params={"part": "status,brandingSettings", "mine": True},
)
data = resp.json()
if data.get("items"):
    ch = data["items"][0]
    print(f"Channel ID     : {ch['id']}")
    print(f"Made for kids  : {ch['status'].get('madeForKids', 'N/A')}")
    print(f"Self declared  : {ch['status'].get('selfDeclaredMadeForKids', 'N/A')}")
    if ch['status'].get('madeForKids') or ch['status'].get('selfDeclaredMadeForKids'):
        print("\n✗ PROBLEM: CHANNEL is marked 'Made for Kids' — comments are disabled on ALL videos on this channel. Must be changed in YouTube Studio.")
    else:
        print("✓ Channel not marked as Made for Kids")
else:
    print("Could not fetch channel details")

# ── 5. Try posting a minimal test comment ─────────────────────────────────────
print(f"\n--- Attempting comment post on {VIDEO_ID} ---")
resp = requests.post(
    "https://www.googleapis.com/youtube/v3/commentThreads",
    headers={**headers, "Content-Type": "application/json"},
    params={"part": "snippet"},
    json={
        "snippet": {
            "videoId": VIDEO_ID,
            "topLevelComment": {
                "snippet": {"textOriginal": "Test"}
            }
        }
    },
    timeout=20,
)
print(f"Status: {resp.status_code}")
print(f"Response: {json.dumps(resp.json(), indent=2)}")
# Save as debug_comment.py
import json
import requests
from dotenv import load_dotenv
load_dotenv()

# Load token
token_data = json.loads(open("youtube_token.json").read())
token = token_data["access_token"]

# Try posting a comment on one of your public videos
video_id = "TQGRe1QeFYw"   # one of your public videos

resp = requests.post(
    "https://www.googleapis.com/youtube/v3/commentThreads",
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    },
    params={"part": "snippet"},
    json={
        "snippet": {
            "videoId": video_id,
            "topLevelComment": {
                "snippet": {"textOriginal": "Test comment"}
            },
        }
    },
    timeout=20,
)

print("Status:", resp.status_code)
print("Response:", json.dumps(resp.json(), indent=2))
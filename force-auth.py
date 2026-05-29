# Run this in your project folder as: python force_auth.py
import os
from dotenv import load_dotenv
load_dotenv()

from youtube_uploader import _load_client_secrets, _device_code_flow

secrets = _load_client_secrets()
if not secrets:
    print("ERROR: client_secrets.json not found or invalid")
else:
    print("client_secrets.json loaded OK")
    print("Starting device code flow...")
    token = _device_code_flow(secrets)
    if token:
        print(f"SUCCESS – token obtained: {token[:20]}...")
    else:
        print("FAILED – check errors above")
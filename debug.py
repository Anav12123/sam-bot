"""
debug.py — Run this on Railway to diagnose the ElevenLabs 401 issue
Usage: add this as a one-off command or check logs after deploy

To run on Railway: 
  Change Procfile temporarily to: web: python debug.py
  Deploy, check logs, then change back to: web: python server.py
"""

import os
import asyncio
import httpx
from dotenv import load_dotenv

load_dotenv()


async def main():
    key = os.environ.get("ELEVENLABS_API_KEY", "NOT SET")
    
    print("=" * 60)
    print("DEBUG: ElevenLabs API Key Analysis")
    print("=" * 60)
    print(f"Key value:  {key}")
    print(f"Key length: {len(key)}")
    print(f"Starts with 'sk_': {key.startswith('sk_')}")
    print(f"Has spaces: {' ' in key}")
    print(f"Has newline: {chr(10) in key or chr(13) in key}")
    print(f"Hex dump of last 5 chars: {[hex(ord(c)) for c in key[-5:]]}")
    print()

    # Test 1: Get user info
    print("TEST 1: GET /v1/user")
    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://api.elevenlabs.io/v1/user",
            headers={"xi-api-key": key}
        )
        print(f"  Status: {r.status_code}")
        print(f"  Response: {r.text[:200]}")
    print()

    # Test 2: List voices
    print("TEST 2: GET /v1/voices")
    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://api.elevenlabs.io/v1/voices",
            headers={"xi-api-key": key}
        )
        print(f"  Status: {r.status_code}")
        print(f"  Response: {r.text[:200]}")
    print()

    # Test 3: TTS with stripped key
    stripped_key = key.strip()
    print(f"TEST 3: TTS with stripped key (len={len(stripped_key)})")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://api.elevenlabs.io/v1/text-to-speech/JBFqnCBsd6RMkjVDRZzb",
            headers={
                "xi-api-key":   stripped_key,
                "Content-Type": "application/json",
            },
            json={
                "text":     "Hello, this is a test.",
                "model_id": "eleven_flash_v2_5",
                "voice_settings": {
                    "stability": 0.35,
                    "similarity_boost": 0.75,
                },
            }
        )
        print(f"  Status: {r.status_code}")
        if r.status_code == 200:
            print(f"  ✅ TTS WORKS! Audio size: {len(r.content)} bytes")
        else:
            print(f"  Response: {r.text[:300]}")
    print()
    print("=" * 60)
    print("DEBUG COMPLETE")
    print("=" * 60)

    # Keep server alive so Railway doesn't restart
    print("Keeping alive for 60s...")
    await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())

"""
Speaker.py
ACTIVE TTS:   Cartesia Sonic-3 (90ms, no server IP restrictions)
INACTIVE TTS: ElevenLabs eleven_flash_v2_5 — commented out
              (blocked on free tier from server IPs)

NOISE MIXING: Commented out — re-enable in websocket_server.py _process()
"""

import os
import base64
import asyncio
import httpx
import io
import hashlib

# Windows-only ffmpeg paths — commented out for Railway (Linux has ffmpeg system-wide)
# os.environ["FFMPEG_BINARY"]  = r"C:\Users\user\Downloads\ffmpeg-8.1-full_build\bin\ffmpeg.exe"
# os.environ["FFPROBE_BINARY"] = r"C:\Users\user\Downloads\ffmpeg-8.1-full_build\bin\ffprobe.exe"

# pydub only needed for noise mixing (disabled)
try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    AudioSegment = None

# ── Noise mixing — available but disabled ────────────────────────────────────
NOISE_FILE   = "freesound_community-office-ambience-24734 (1).mp3"
NOISE_SLICES = 20


def _mix_noise(voice_bytes: bytes, noise_slices: list, text: str) -> tuple[bytes, int]:
    if not PYDUB_AVAILABLE:
        return voice_bytes, len(voice_bytes) // 32
    try:
        voice       = AudioSegment.from_file(io.BytesIO(voice_bytes)).fade_in(80)
        duration_ms = len(voice)
        hash_val    = int(hashlib.md5(text.encode()).hexdigest(), 16)
        slice_idx   = hash_val % len(noise_slices)
        noise_seg   = noise_slices[slice_idx]
        loops       = (duration_ms // len(noise_seg)) + 2
        noise       = (noise_seg * loops)[:duration_ms]
        noise       = noise + 3
        noise       = noise.low_pass_filter(4000)
        combined    = voice.overlay(noise, gain_during_overlay=-3)
        output      = io.BytesIO()
        combined.export(output, format="mp3", bitrate="64k")
        print("[Speaker] Ambience added")
        return output.getvalue(), duration_ms
    except Exception as e:
        print(f"[Speaker] Noise failed: {e}")
        return voice_bytes, get_duration_ms(voice_bytes)


def get_duration_ms(audio_bytes: bytes) -> int:
    if not PYDUB_AVAILABLE:
        return int((len(audio_bytes) * 8) / (48 * 1000) * 1000)
    try:
        seg = AudioSegment.from_file(io.BytesIO(audio_bytes))
        return len(seg)
    except Exception:
        return int((len(audio_bytes) * 8) / (48 * 1000) * 1000)


# ── Cartesia config (ACTIVE) ──────────────────────────────────────────────────
CARTESIA_VOICE_ID = "79a125e8-cd45-4c13-8a67-188112f4dd22"  # British Narration Lady
# Other voices:
# "a0e99841-438c-4a64-b679-ae501e7d6091"  — Default
# "694f9389-aac1-45b6-b726-9d9369183238"  — Barbershop Man (deep)
CARTESIA_MODEL    = "sonic-turbo"   # sonic-turbo: 40ms first byte, optimised for conversation

# ── ElevenLabs config (INACTIVE — blocked on free tier from server IPs) ───────
# ELEVENLABS_URL      = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
# ELEVENLABS_MODEL    = "eleven_flash_v2_5"
# ELEVENLABS_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"  # George

# ── Recall.ai config ──────────────────────────────────────────────────────────
RECALL_REGION   = os.environ.get("RECALLAI_REGION", "ap-northeast-1")
RECALL_API_BASE = f"https://{RECALL_REGION}.recall.ai/api/v1"


class CartesiaSpeaker:
    def __init__(self, bot_id: str = None):
        self.cartesia_key = os.environ["CARTESIA_API_KEY"]
        self.recall_key   = os.environ["RECALLAI_API_KEY"]
        # self.elevenlabs_key = os.environ["ELEVENLABS_API_KEY"]  # uncomment to re-enable
        self.bot_id       = bot_id

        print(f"[Speaker] Cartesia key: {self.cartesia_key[:8]}...{self.cartesia_key[-4:]} (len={len(self.cartesia_key)})")

        # Noise slices — pre-loaded, not used until re-enabled
        base_dir   = os.path.dirname(os.path.abspath(__file__))
        noise_path = os.path.join(base_dir, NOISE_FILE)
        self._noise_slices = []
        try:
            if not PYDUB_AVAILABLE:
                raise ImportError("pydub not available")
            full_noise = AudioSegment.from_file(noise_path)
            slice_len  = len(full_noise) // NOISE_SLICES
            self._noise_slices = [
                full_noise[i * slice_len:(i + 1) * slice_len]
                for i in range(NOISE_SLICES)
            ]
            print(f"[Speaker] Noise pre-sliced into {NOISE_SLICES} chunks ({slice_len}ms each)")
        except Exception as e:
            print(f"[Speaker] Noise load failed (not critical): {e}")

        self._base_noise = self._noise_slices if self._noise_slices else None

        limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)

        # ── ACTIVE: Cartesia client ───────────────────────────────────────────
        self._cartesia_client  = httpx.AsyncClient(timeout=30, limits=limits)
        self._cartesia_headers = {
            "Authorization":    f"Bearer {self.cartesia_key}",
            "Cartesia-Version": "2025-04-16",
            "Content-Type":     "application/json",
        }

        # ── INACTIVE: ElevenLabs client ───────────────────────────────────────
        # self._elevenlabs_client  = httpx.AsyncClient(timeout=30, limits=limits)
        # self._elevenlabs_headers = {
        #     "xi-api-key":   self.elevenlabs_key,
        #     "Content-Type": "application/json",
        # }

        # Recall inject client
        self._recall_client  = httpx.AsyncClient(timeout=30, limits=limits)
        self._recall_headers = {
            "Authorization": f"Token {self.recall_key}",
            "Content-Type":  "application/json",
            "accept":        "application/json",
        }

    # ── ACTIVE: Cartesia Sonic-3 TTS ──────────────────────────────────────────
    async def _synthesise(self, text: str) -> bytes:
        """Cartesia Sonic-3 bytes endpoint."""
        response = await self._cartesia_client.post(
            "https://api.cartesia.ai/tts/bytes",
            headers=self._cartesia_headers,
            json={
                "model_id":   CARTESIA_MODEL,
                "transcript": text,
                "voice":      {"mode": "id", "id": CARTESIA_VOICE_ID},
                "language":   "en",
                "output_format": {
                    "container":   "mp3",
                    "sample_rate": 44100,
                    "bit_rate":    128000,
                },
            },
        )
        response.raise_for_status()
        return response.content

    # ── INACTIVE: ElevenLabs TTS ──────────────────────────────────────────────
    # Blocked on free tier from server IPs — upgrade to paid to re-enable
    # To switch back:
    #   1. Comment out Cartesia _synthesise above
    #   2. Uncomment this method
    #   3. Uncomment elevenlabs_key and _elevenlabs_client in __init__
    #
    # async def _synthesise(self, text: str) -> bytes:
    #     """ElevenLabs eleven_flash_v2_5."""
    #     response = await self._elevenlabs_client.post(
    #         ELEVENLABS_URL.format(voice_id=ELEVENLABS_VOICE_ID),
    #         headers=self._elevenlabs_headers,
    #         json={
    #             "text":     text,
    #             "model_id": ELEVENLABS_MODEL,
    #             "voice_settings": {
    #                 "stability":         0.35,
    #                 "similarity_boost":  0.75,
    #                 "style":             0.0,
    #                 "use_speaker_boost": True,
    #             },
    #             "output_format": "mp3_44100_64",
    #         },
    #     )
    #     response.raise_for_status()
    #     return response.content

    async def _inject_into_meeting(self, b64_audio: str):
        if not self.bot_id:
            print("[Speaker] No bot_id — skipping inject")
            return
        payload  = {"kind": "mp3", "b64_data": b64_audio}
        response = await self._recall_client.post(
            f"{RECALL_API_BASE}/bot/{self.bot_id}/output_audio/",
            headers=self._recall_headers,
            json=payload,
        )
        if response.status_code not in (200, 201):
            print(f"[Speaker] Inject error {response.status_code}: {response.text}")
        else:
            print("[Speaker] Audio injected")

    async def close(self):
        await asyncio.gather(
            self._cartesia_client.aclose(),
            self._recall_client.aclose(),
            # self._elevenlabs_client.aclose(),  # uncomment if ElevenLabs re-enabled
        )

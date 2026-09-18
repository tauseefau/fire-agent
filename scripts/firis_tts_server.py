#!/usr/bin/env python3
"""FIRIS local STT + TTS microservice (fully local, zero ElevenLabs credits).

STT  (speech-to-text):   whisper.cpp via pywhispercpp (base.en model)
TTS  (text-to-speech):   Edge-TTS Microsoft neural voices

Endpoints:
  GET   /health                        -> {"ok":true}
  GET   /voices                        -> available neural TTS voices
  GET   /tts?text=...&voice=...&rate=+4%  -> audio/mpeg stream
  POST  /stt  (raw audio body, or JSON {"audio_b64": "..."}) -> {"text": "..."}
  GET   /stt-status                    -> {"model": "...", "loaded": bool}
"""
import argparse, json, os, base64, tempfile, subprocess, threading, io
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

VOICES = [
    {"name": "en-AU-WilliamMultilingualNeural", "gender": "Male",   "style": "Australian, authoritative"},
    {"name": "en-AU-NatashaNeural",            "gender": "Female",   "style": "Australian, friendly"},
    {"name": "en-US-ChristopherNeural",        "gender": "Male",   "style": "US, news-anchor authority"},
    {"name": "en-US-AndrewNeural",             "gender": "Male",   "style": "US, calm confident"},
    {"name": "en-GB-RyanNeural",               "gender": "Male",   "style": "UK, calm"},
]

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
PARENT  = os.path.dirname(SCRIPTS)
VENV_PY = os.path.join(PARENT, "tts-venv", "bin", "python")
MODEL_DIR = os.path.join(PARENT, "tts-venv", "models")
MODEL_PATH = os.path.join(MODEL_DIR, "ggml-base.en.bin")

# Whisper is heavyweight; load once, lazily, guarded by a lock.
_stt_model = None
_stt_lock = threading.Lock()

def get_stt_model():
    global _stt_model
    if _stt_model is None:
        with _stt_lock:
            if _stt_model is None:
                from pywhispercpp.model import Model
                _stt_model = Model(MODEL_PATH, n_threads=4, no_context=True, print_realtime=False, print_progress=False)
    return _stt_model

def transcribe_audio_bytes(data: bytes) -> str:
    """Transcribe raw audio bytes via local whisper.cpp.
    Converts any input (mp3/webm/opus) to 16kHz mono WAV with ffmpeg first."""
    model = get_stt_model()
    with tempfile.NamedTemporaryFile(suffix=".in", delete=False) as f:
        src = f.name
        f.write(data)
    wav = src + ".wav"
    try:
        conv = subprocess.run(
            ["ffmpeg", "-y", "-i", src, "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav],
            capture_output=True, timeout=60)
        if conv.returncode != 0 or not os.path.exists(wav):
            return ""
        segs = model.transcribe(wav)
        parts = []
        for s in (segs or []):
            try:
                t = getattr(s, "text", None) or str(s)
            except Exception:
                t = str(s)
            t = t.strip()
            if t:
                parts.append(t)
        return " ".join(parts).strip()
    finally:
        for p in (src, wav):
            try:
                os.remove(p)
            except OSError:
                pass


class FirisHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def _json(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path); path = u.path; qs = parse_qs(u.query)
        if path == "/health":
            return self._json({"ok": True, "service": "firis-stt-tts",
                               "stt_model": os.path.basename(MODEL_PATH) if os.path.exists(MODEL_PATH) else None,
                               "tts_voices": len(VOICES)})
        if path == "/voices":
            return self._json({"voices": VOICES})
        if path == "/stt-status":
            return self._json({"model": os.path.basename(MODEL_PATH) if os.path.exists(MODEL_PATH) else None,
                               "loaded": _stt_model is not None})
        if path == "/tts":
            text = (qs.get("text", [""])[0] or "").strip()
            if not text:
                return self._json({"error": "text required"}, 400)
            voice = qs.get("voice", ["en-AU-WilliamMultilingualNeural"])[0]
            rate = qs.get("rate", ["+0%"])[0]
            safe_text = text.encode("unicode_escape").decode()
            safe_voice = voice.replace("'", "")
            script = (
                "import asyncio, edge_tts, sys\n"
                "async def m():\n"
                f"  c = edge_tts.Communicate(sys.argv[1], sys.argv[2], rate=sys.argv[3])\n"
                "  await c.save(sys.argv[4])\n"
                "asyncio.run(m())\n"
            )
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                out = f.name
            cmd = [VENV_PY, "-c", script, text, safe_voice, rate, out]
            proc = subprocess.run(cmd, capture_output=True, timeout=30)
            if proc.returncode != 0 or not os.path.exists(out):
                return self._json({"error": "tts failed: " + (proc.stderr.decode()[-200:])}, 500)
            with open(out, "rb") as ag:
                audio = ag.read()
            os.remove(out)
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(audio)))
            self.end_headers()
            self.wfile.write(audio)
            return
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        u = urlparse(self.path); path = u.path
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        if path == "/stt":
            data = raw
            ctype = self.headers.get("Content-Type", "")
            print(f"[STT DEBUG] Raw: {len(raw)} bytes, Content-Type: '{ctype}'", flush=True)
            print(f"[STT DEBUG] Raw first 100: {raw[:100]}", flush=True)
            if "json" in ctype.lower():
                try:
                    obj = json.loads(raw.decode())
                except Exception:
                    obj = {}
                b64 = obj.get("audio_b64")
                if b64:
                    data = base64.b64decode(b64)
            elif "multipart" in ctype.lower():
                import cgi
                environ = {'REQUEST_METHOD': 'POST', 'CONTENT_TYPE': ctype, 'CONTENT_LENGTH': str(len(raw))}
                fs = cgi.FieldStorage(fp=io.BytesIO(raw), environ=environ, keep_blank_values=True)
                print(f"[STT DEBUG] FieldStorage keys: {list(fs.keys())}", flush=True)
                audio_field = fs.getfirst('audio')
                print(f"[STT DEBUG] audio_field type: {type(audio_field)}, value: {repr(audio_field)[:100]}", flush=True)
                # FieldStorage returns list for multiple values, or bytes if single
                if isinstance(audio_field, list):
                    # Take the first one
                    audio_field = audio_field[0] if audio_field else None
                if audio_field is not None:
                    if hasattr(audio_field, 'file') and audio_field.file:
                        data = audio_field.file.read()
                        print(f"[STT DEBUG] Read from file: {len(data)} bytes", flush=True)
                    elif hasattr(audio_field, 'value') and audio_field.value:
                        data = audio_field.value
                        print(f"[STT DEBUG] Read from value: {len(data)} bytes", flush=True)
                    elif isinstance(audio_field, (bytes, bytearray)):
                        data = audio_field
                        print(f"[STT DEBUG] Direct bytes: {len(data)} bytes", flush=True)
                print(f"[STT DEBUG] After multipart parse: {len(data)} bytes", flush=True)
            if not data:
                return self._json({"error": "audio body required"}, 400)
            try:
                text = transcribe_audio_bytes(data)
                print(f"[STT DEBUG] Transcribed: '{text}'", flush=True)
                return self._json({"text": text})
            except Exception as e:
                print(f"[STT DEBUG] Error: {e}", flush=True)
                return self._json({"error": "stt failed: " + str(e)}, 500)
        return self._json({"error": "not found"}, 404)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8002)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    print(f"FIRIS STT+TTS microservice on http://{args.host}:{args.port} "
          f"(model={'present' if os.path.exists(MODEL_PATH) else 'MISSING'}, voices={len(VOICES)})", flush=True)
    HTTPServer((args.host, args.port), FirisHandler).serve_forever()

if __name__ == "__main__":
    main()
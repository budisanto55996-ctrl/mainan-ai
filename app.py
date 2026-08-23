from flask import Flask, request, jsonify, send_from_directory, abort
import os
import uuid
import asyncio
import time
import wave
import threading
from groq import Groq
import edge_tts

app = Flask(__name__)

# Gunakan /tmp untuk Vercel (karena filesystem-nya read-only), atau static untuk lokal
AUDIO_DIR = "/tmp/static" if os.environ.get("VERCEL") else "static"

MAX_UPLOAD_SIZE = 3 * 1024 * 1024
FILE_MAX_AGE = 600
MIN_FILE_AGE = 120
MAX_AUDIO_SECONDS = 15
MAX_TOKENS = 100

cleanup_lock = threading.Lock()
os.makedirs(AUDIO_DIR, exist_ok=True)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

ALLOWED_AUDIO_PREFIX = ("input_", "response_")

def cleanup_old_files():
    if not cleanup_lock.acquire(blocking=False):
        return
    try:
        now = time.time()
        for filename in os.listdir(AUDIO_DIR):
            if not filename.startswith(ALLOWED_AUDIO_PREFIX):
                continue
            file_path = os.path.join(AUDIO_DIR, filename)
            if not os.path.isfile(file_path):
                continue
            try:
                file_age = now - os.path.getmtime(file_path)
                if file_age > FILE_MAX_AGE:
                    os.remove(file_path)
            except Exception:
                pass
    finally:
        cleanup_lock.release()

def validate_wav(file_path):
    try:
        with wave.open(file_path, "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            frames = wav.getnframes()

            if channels <= 0 or sample_width <= 0 or sample_rate <= 0 or frames <= 0:
                return False, "Format WAV tidak valid"

            duration = frames / float(sample_rate)
            if duration > MAX_AUDIO_SECONDS:
                return False, f"Durasi audio terlalu panjang (maksimal {MAX_AUDIO_SECONDS} detik)."
            return True, None
    except Exception as e:
        return False, f"Gagal membaca WAV: {str(e)}"

async def generate_edge_tts(text, output_path):
    communicate = edge_tts.Communicate(text=text, voice="id-ID-GadisNeural", rate="+10%", pitch="+15Hz")
    await communicate.save(output_path)

def run_tts(text, output_path):
    asyncio.run(generate_edge_tts(text, output_path))

@app.route("/")
def home():
    return jsonify({
        "status": "online",
        "server": "Mainan AI Server Vercel",
        "message": "Server aktif"
    })

@app.route("/health")
def health():
    return jsonify({"status": "healthy", "groq": "configured" if groq_client else "not_configured"})

@app.route("/voice-chat", methods=["POST"])
def voice_chat():
    input_path = None
    output_path = None
    request_id = str(uuid.uuid4())
    start_time = time.time()

    try:
        cleanup_old_files()

        if not groq_client:
            return jsonify({"status": "error", "error": "GROQ_API_KEY belum diatur"}), 500

        wav_data = request.get_data(cache=False)
        if not wav_data or len(wav_data) > MAX_UPLOAD_SIZE:
            return jsonify({"status": "error", "error": "Audio tidak valid atau terlalu besar (>3MB)"}), 400

        input_filename = f"input_{request_id}.wav"
        input_path = os.path.join(AUDIO_DIR, input_filename)

        with open(input_path, "wb") as f:
            f.write(wav_data)

        valid_wav, wav_error = validate_wav(input_path)
        if not valid_wav:
            return jsonify({"status": "error", "error": wav_error}), 400

        # Whisper STT
        with open(input_path, "rb") as audio_file:
            transcript = groq_client.audio.transcriptions.create(
                model="whisper-large-v3-turbo",
                file=audio_file,
                language="id"
            )
        user_text = transcript.text.strip()

        if not user_text:
            return jsonify({"status": "error", "error": "Suara tidak terdeteksi"}), 400

        # Llama AI
        chat_completion = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": "Kamu adalah robot anak perempuan yang ceria, lucu, ramah. Jawab maksimal 2 kalimat pendek tanpa emoji/markdown."
                },
                {"role": "user", "content": user_text}
            ],
            temperature=0.7,
            max_tokens=MAX_TOKENS
        )
        ai_reply = chat_completion.choices[0].message.content.strip()

        # Edge TTS
        output_filename = f"response_{request_id}.mp3"
        output_path = os.path.join(AUDIO_DIR, output_filename)
        run_tts(ai_reply, output_path)

        audio_url = request.host_url.rstrip("/") + f"/audio/{output_filename}"
        total_time = time.time() - start_time

        return jsonify({
            "status": "success",
            "request_id": request_id,
            "user_text": user_text,
            "ai_reply": ai_reply,
            "audio_url": audio_url,
            "processing_time": round(total_time, 2)
        })

    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

    finally:
        if input_path and os.path.exists(input_path):
            try:
                os.remove(input_path)
            except:
                pass

@app.route("/audio/<path:filename>", methods=["GET"])
def serve_audio(filename):
    if not filename.startswith("response_") or not filename.endswith(".mp3"):
        abort(404)
    if not os.path.isfile(os.path.join(AUDIO_DIR, filename)):
        abort(404)
    return send_from_directory(AUDIO_DIR, filename)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
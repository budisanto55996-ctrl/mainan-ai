from flask import Flask, request, jsonify, send_from_directory, abort
import os
import uuid
import asyncio
import time
import wave
import threading
from groq import Groq
import edge_tts

# =========================================================
# FLASK
# =========================================================

app = Flask(__name__)

# =========================================================
# KONFIGURASI PRODUCTION
# =========================================================

AUDIO_DIR = "static"

# Maksimum WAV yang boleh diterima (3 MB)
MAX_UPLOAD_SIZE = 3 * 1024 * 1024

# MP3 hasil TTS akan dipertahankan minimal 10 menit
FILE_MAX_AGE = 600

# File yang baru dibuat tidak boleh dihapus oleh cleanup sebelum umur minimum ini
MIN_FILE_AGE = 120

# Maksimum durasi audio WAV (detik)
MAX_AUDIO_SECONDS = 15

# Maksimum jumlah token AI
MAX_TOKENS = 100

# Lock untuk proses cleanup
cleanup_lock = threading.Lock()

# Membuat folder audio
os.makedirs(AUDIO_DIR, exist_ok=True)

# =========================================================
# GROQ
# =========================================================

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

if not GROQ_API_KEY:
    print("WARNING: GROQ_API_KEY belum diatur!")

groq_client = None

if GROQ_API_KEY:
    groq_client = Groq(
        api_key=GROQ_API_KEY
    )

# =========================================================
# ALLOWED FILE
# =========================================================

ALLOWED_AUDIO_PREFIX = (
    "input_",
    "response_"
)

# =========================================================
# CLEANUP FILE LAMA
# =========================================================

def cleanup_old_files():
    """
    Menghapus file audio lama.
    Perlindungan:
    - hanya file input_ dan response_
    - umur file > 10 menit
    - file baru tidak disentuh
    - menggunakan lock agar tidak bentrok
    """
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

                if file_age < MIN_FILE_AGE:
                    continue

                if file_age > FILE_MAX_AGE:
                    try:
                        os.remove(file_path)
                        print("CLEANUP:", filename)
                    except FileNotFoundError:
                        pass

            except Exception as e:
                print("Cleanup file error:", filename, str(e))

    finally:
        cleanup_lock.release()


# =========================================================
# VALIDASI WAV
# =========================================================

def validate_wav(file_path):
    """
    Memastikan file benar-benar WAV dan durasinya tidak terlalu panjang.
    """
    try:
        with wave.open(file_path, "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            frames = wav.getnframes()

            if channels <= 0:
                return False, "Channel WAV tidak valid"

            if sample_width <= 0:
                return False, "Bit depth WAV tidak valid"

            if sample_rate <= 0:
                return False, "Sample rate WAV tidak valid"

            if frames <= 0:
                return False, "WAV tidak memiliki audio"

            duration = frames / float(sample_rate)

            print(
                "WAV:", channels, "channel,", sample_rate, "Hz,",
                sample_width * 8, "bit,", round(duration, 2), "detik"
            )

            if duration > MAX_AUDIO_SECONDS:
                return False, f"Durasi audio terlalu panjang. Maksimal {MAX_AUDIO_SECONDS} detik."

            return True, None

    except wave.Error as e:
        return False, f"File bukan WAV valid: {str(e)}"

    except Exception as e:
        return False, f"Gagal membaca WAV: {str(e)}"


# =========================================================
# EDGE TTS
# =========================================================

async def generate_edge_tts(text, output_path):
    voice = "id-ID-GadisNeural"

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate="+10%",
        pitch="+15Hz"
    )

    await communicate.save(output_path)


def run_tts(text, output_path):
    """
    Menjalankan Edge-TTS dengan event loop baru.
    """
    asyncio.run(generate_edge_tts(text, output_path))


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():
    return jsonify({
        "status": "online",
        "server": "Mainan AI Server",
        "version": "production",
        "stt": "Groq Whisper",
        "ai": "Groq Llama",
        "tts": "Edge-TTS",
        "message": "Server aktif"
    })


# =========================================================
# HEALTH CHECK
# =========================================================

@app.route("/health")
def health():
    return jsonify({
        "status": "healthy",
        "groq": "configured" if groq_client else "not_configured",
        "timestamp": int(time.time())
    })


# =========================================================
# VOICE CHAT
# =========================================================

@app.route("/voice-chat", methods=["POST"])
def voice_chat():
    input_path = None
    output_path = None
    request_id = str(uuid.uuid4())
    start_time = time.time()

    try:
        print("\n========================================")
        print("VOICE REQUEST:", request_id)
        print("========================================")

        # Cleanup file lama
        cleanup_old_files()

        if groq_client is None:
            return jsonify({
                "status": "error",
                "error": "GROQ_API_KEY belum diatur di Render"
            }), 500

        content_length = request.content_length
        if content_length is not None and content_length > MAX_UPLOAD_SIZE:
            return jsonify({
                "status": "error",
                "error": f"Ukuran audio terlalu besar. Maksimal {MAX_UPLOAD_SIZE // (1024 * 1024)} MB."
            }), 413

        wav_data = request.get_data(cache=False)
        if not wav_data:
            return jsonify({
                "status": "error",
                "error": "Tidak ada data audio"
            }), 400

        if len(wav_data) > MAX_UPLOAD_SIZE:
            return jsonify({
                "status": "error",
                "error": "Ukuran audio melebihi batas 3 MB."
            }), 413

        if len(wav_data) < 44:
            return jsonify({
                "status": "error",
                "error": "Audio terlalu kecil atau bukan WAV."
            }), 400

        print("Audio diterima:", len(wav_data), "bytes")

        # Simpan WAV sementara
        input_filename = f"input_{request_id}.wav"
        input_path = os.path.join(AUDIO_DIR, input_filename)

        with open(input_path, "wb") as f:
            f.write(wav_data)

        # Validasi WAV
        valid_wav, wav_error = validate_wav(input_path)
        if not valid_wav:
            return jsonify({
                "status": "error",
                "error": wav_error
            }), 400

        # Whisper (STT)
        print("Memproses Groq Whisper...")
        whisper_start = time.time()

        with open(input_path, "rb") as audio_file:
            transcript = groq_client.audio.transcriptions.create(
                model="whisper-large-v3-turbo",
                file=audio_file,
                language="id"
            )

        whisper_time = time.time() - whisper_start
        user_text = transcript.text.strip()
        print("Whisper:", round(whisper_time, 2), "detik")
        print("PENGGUNA:", user_text)

        if not user_text:
            return jsonify({
                "status": "error",
                "error": "Suara tidak terdeteksi"
            }), 400

        # AI Llama
        print("Mengirim ke Groq Llama...")
        ai_start = time.time()

        chat_completion = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Kamu adalah robot anak perempuan yang ceria, lucu, ramah dan pintar untuk anak-anak. "
                        "Gunakan bahasa Indonesia santai dan mudah dipahami. "
                        "Jawab maksimal 2 kalimat pendek. "
                        "Jangan menggunakan emoji, simbol aneh, markdown, atau penjelasan panjang."
                    )
                },
                {
                    "role": "user",
                    "content": user_text
                }
            ],
            temperature=0.7,
            max_tokens=MAX_TOKENS
        )

        ai_time = time.time() - ai_start
        ai_reply = chat_completion.choices[0].message.content.strip()
        print("AI:", ai_reply)
        print("AI time:", round(ai_time, 2), "detik")

        if not ai_reply:
            return jsonify({
                "status": "error",
                "error": "AI tidak memberikan jawaban"
            }), 500

        # Edge TTS
        output_filename = f"response_{request_id}.mp3"
        output_path = os.path.join(AUDIO_DIR, output_filename)

        print("Membuat suara AI...")
        tts_start = time.time()
        run_tts(ai_reply, output_path)
        tts_time = time.time() - tts_start
        print("TTS time:", round(tts_time, 2), "detik")

        if not os.path.exists(output_path) or os.path.getsize(output_path) <= 0:
            return jsonify({
                "status": "error",
                "error": "File MP3 gagal dibuat"
            }), 500

        output_size = os.path.getsize(output_path)
        audio_url = request.host_url.rstrip("/") + "/static/" + output_filename
        total_time = time.time() - start_time

        print("\n========================================")
        print("VOICE CHAT BERHASIL")
        print("REQUEST:", request_id)
        print("USER:", user_text)
        print("AI:", ai_reply)
        print("AUDIO:", audio_url)
        print("MP3:", output_size, "bytes")
        print("TOTAL:", round(total_time, 2), "detik")
        print("========================================")

        # Hapus file WAV input sementara
        try:
            if input_path and os.path.exists(input_path):
                os.remove(input_path)
                input_path = None
        except Exception as e:
            print("Gagal menghapus WAV:", e)

        return jsonify({
            "status": "success",
            "request_id": request_id,
            "user_text": user_text,
            "ai_reply": ai_reply,
            "audio_url": audio_url,
            "audio_size": output_size,
            "processing_time": round(total_time, 2)
        })

    except Exception as e:
        print("\n========================================")
        print("VOICE CHAT ERROR")
        print("REQUEST:", request_id)
        print("ERROR:", str(e))
        print("========================================")

        return jsonify({
            "status": "error",
            "request_id": request_id,
            "error": str(e)
        }), 500

    finally:
        try:
            if input_path and os.path.exists(input_path):
                os.remove(input_path)
        except Exception as e:
            print("Final WAV cleanup error:", e)

        try:
            cleanup_old_files()
        except Exception as e:
            print("Final cleanup error:", e)


# =========================================================
# DOWNLOAD / STREAM MP3
# =========================================================

@app.route("/static/<path:filename>", methods=["GET"])
def serve_audio(filename):
    if not filename.startswith("response_"):
        abort(404)

    if not filename.endswith(".mp3"):
        abort(404)

    file_path = os.path.join(AUDIO_DIR, filename)

    if not os.path.isfile(file_path):
        abort(404)

    return send_from_directory(AUDIO_DIR, filename)


# =========================================================
# START SERVER
# =========================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("========================================")
    print("MAINAN AI SERVER AKTIF")
    print("Port:", port)
    print("========================================")
    app.run(host="0.0.0.0", port=port)
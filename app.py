from flask import Flask, request, jsonify, send_from_directory
import os
import uuid
import asyncio

import google.generativeai as genai
import edge_tts
from groq import Groq


app = Flask(__name__)

# =========================================================
# FOLDER AUDIO
# =========================================================

AUDIO_DIR = "static"
os.makedirs(AUDIO_DIR, exist_ok=True)


# =========================================================
# API KEY DARI ENVIRONMENT VARIABLE
# =========================================================

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")


# =========================================================
# CEK API KEY
# =========================================================

if not GEMINI_API_KEY:
    print("PERINGATAN: GEMINI_API_KEY belum diatur!")

if not GROQ_API_KEY:
    print("PERINGATAN: GROQ_API_KEY belum diatur!")


# =========================================================
# KONFIGURASI GEMINI
# =========================================================

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

model = genai.GenerativeModel("gemini-3.6-flash")


# =========================================================
# GROQ - WHISPER (SPEECH TO TEXT)
# =========================================================

groq_client = None

if GROQ_API_KEY:
    groq_client = Groq(api_key=GROQ_API_KEY)


# =========================================================
# FUNGSI EDGE-TTS (SUARA ANAK PEREMPUAN CERIA)
# =========================================================

async def generate_edge_tts(text, output_path):
    # Menggunakan suara anak/remaja perempuan ceria (id-ID-GadisNeural)
    voice = "id-ID-GadisNeural"
    communicate = edge_tts.Communicate(text, voice, rate="+15%", pitch="+15Hz")
    await communicate.save(output_path)


# =========================================================
# HALAMAN UTAMA (MENAMPILKAN WEB INTERAKTIF)
# =========================================================

@app.route("/")
def home():
    return send_from_directory(".", "index.html")


# =========================================================
# VOICE CHAT
# =========================================================

@app.route("/voice-chat", methods=["POST"])
def voice_chat():

    try:

        # -------------------------------------------------
        # CEK API
        # -------------------------------------------------

        if groq_client is None:
            return jsonify({
                "status": "error",
                "error": "GROQ_API_KEY belum diatur di server"
            }), 500

        if not GEMINI_API_KEY:
            return jsonify({
                "status": "error",
                "error": "GEMINI_API_KEY belum diatur di server"
            }), 500

        # -------------------------------------------------
        # 1. TERIMA AUDIO WAV DARI KLIEN
        # -------------------------------------------------

        wav_data = request.data

        if not wav_data:
            return jsonify({
                "status": "error",
                "error": "Audio kosong"
            }), 400

        if len(wav_data) < 44:
            return jsonify({
                "status": "error",
                "error": "Audio WAV tidak valid"
            }), 400

        print()
        print("========================================")
        print("AUDIO DITERIMA DARI KLIEN")
        print("Ukuran:", len(wav_data), "bytes")
        print("========================================")

        # -------------------------------------------------
        # 2. SIMPAN FILE WAV
        # -------------------------------------------------

        input_filename = "input_" + str(uuid.uuid4()) + ".wav"
        input_path = os.path.join(AUDIO_DIR, input_filename)

        with open(input_path, "wb") as f:
            f.write(wav_data)

        # -------------------------------------------------
        # 3. SPEECH TO TEXT - GROQ WHISPER
        # -------------------------------------------------

        print("Memproses suara dengan Groq Whisper...")

        with open(input_path, "rb") as audio_file:
            transcript = groq_client.audio.transcriptions.create(
                model="whisper-large-v3-turbo",
                file=audio_file,
                language="id"
            )

        user_text = transcript.text.strip()

        print()
        print("PENGGUNA:")
        print(user_text)

        if not user_text:
            return jsonify({
                "status": "error",
                "error": "Suara tidak terdeteksi"
            }), 400

        # -------------------------------------------------
        # 4. GEMINI AI
        # -------------------------------------------------

        prompt = f"""
Kamu adalah mainan robot AI untuk anak-anak berkarakter anak perempuan yang sangat ceria, lucu, dan ramah.

Sifatmu:
- riang dan gembira
- menggunakan bahasa Indonesia yang santai dan ramah anak
- tidak boleh menggunakan kata kasar
- tidak boleh memberikan konten berbahaya

Jawab sangat singkat.
Maksimal 2 kalimat.

Pertanyaan anak:

{user_text}
"""

        print("Mengirim pertanyaan ke Gemini...")

        response = model.generate_content(prompt)
        ai_reply = response.text.strip()

        print()
        print("AI:")
        print(ai_reply)

        if not ai_reply:
            return jsonify({
                "status": "error",
                "error": "Gemini tidak memberikan jawaban"
            }), 500

        # -------------------------------------------------
        # 5. TEXT TO SPEECH (EDGE-TTS)
        # -------------------------------------------------

        output_filename = "response_" + str(uuid.uuid4()) + ".mp3"
        output_path = os.path.join(AUDIO_DIR, output_filename)

        print("Membuat suara AI (Anak Perempuan Ceria)...")

        # Menjalankan edge-tts secara sinkron di Flask
        asyncio.run(generate_edge_tts(ai_reply, output_path))

        # -------------------------------------------------
        # 6. URL AUDIO
        # -------------------------------------------------

        audio_url = (
            request.host_url.rstrip("/")
            + "/static/"
            + output_filename
        )

        print()
        print("AUDIO AI:")
        print(audio_url)

        # -------------------------------------------------
        # 7. KIRIM HASIL KE KLIEN
        # -------------------------------------------------

        return jsonify({
            "status": "success",
            "user_text": user_text,
            "ai_reply": ai_reply,
            "audio_url": audio_url
        })

    except Exception as e:

        print()
        print("========================================")
        print("ERROR")
        print(str(e))
        print("========================================")

        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


# =========================================================
# FILE AUDIO MP3
# =========================================================

@app.route("/static/<path:filename>")
def serve_audio(filename):
    return send_from_directory(
        AUDIO_DIR,
        filename
    )


# =========================================================
# RUN SERVER
# =========================================================

if __name__ == "__main__":
    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
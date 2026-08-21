from flask import Flask, request, jsonify, send_from_directory
import os
import uuid
import asyncio
from groq import Groq
import edge_tts

app = Flask(__name__)

# =========================================================
# FOLDER AUDIO
# =========================================================
AUDIO_DIR = "static"
os.makedirs(AUDIO_DIR, exist_ok=True)

# =========================================================
# API KEY DARI ENVIRONMENT VARIABLE
# =========================================================
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# =========================================================
# CEK API KEY
# =========================================================
if not GROQ_API_KEY:
    print("PERINGATAN: GROQ_API_KEY belum diatur!")

# Inisialisasi Groq Client
groq_client = None
if GROQ_API_KEY:
    groq_client = Groq(api_key=GROQ_API_KEY)

# =========================================================
# FUNGSI EDGE-TTS (SUARA ANAK PEREMPUAN CERIA)
# =========================================================
async def generate_edge_tts(text, output_path):
    voice = "id-ID-GadisNeural"
    communicate = edge_tts.Communicate(text, voice, rate="+15%", pitch="+15Hz")
    await communicate.save(output_path)

# =========================================================
# HALAMAN UTAMA
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
        if groq_client is None:
            return jsonify({
                "status": "error",
                "error": "GROQ_API_KEY belum diatur di server"
            }), 500

        wav_data = request.data
        if not wav_data or len(wav_data) < 44:
            return jsonify({
                "status": "error",
                "error": "Audio WAV tidak valid"
            }), 400

        # Simpan file WAV
        input_filename = "input_" + str(uuid.uuid4()) + ".wav"
        input_path = os.path.join(AUDIO_DIR, input_filename)
        with open(input_path, "wb") as f:
            f.write(wav_data)

        # 1. Speech to Text - Groq Whisper
        with open(input_path, "rb") as audio_file:
            transcript = groq_client.audio.transcriptions.create(
                model="whisper-large-v3-turbo",
                file=audio_file,
                language="id"
            )
        user_text = transcript.text.strip()

        if not user_text:
            return jsonify({
                "status": "error",
                "error": "Suara tidak terdeteksi"
            }), 400

        # 2. Groq AI - Menggunakan model openai/gpt-oss-20b
        chat_completion = groq_client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": "Kamu adalah mainan robot AI untuk anak-anak berkarakter anak perempuan yang sangat ceria, lucu, dan ramah. Gunakan bahasa Indonesia yang santai dan ramah anak. Jangan pakai kata kasar. Jawab sangat singkat maksimal 2 kalimat.\n\nPertanyaan anak: " + user_text
                }
            ],
            model="openai/gpt-oss-20b",
        )
        ai_reply = chat_completion.choices[0].message.content.strip()

        # 3. Text to Speech (Edge-TTS)
        output_filename = "response_" + str(uuid.uuid4()) + ".mp3"
        output_path = os.path.join(AUDIO_DIR, output_filename)
        
        asyncio.run(generate_edge_tts(ai_reply, output_path))

        audio_url = request.host_url.rstrip("/") + "/static/" + output_filename

        return jsonify({
            "status": "success",
            "user_text": user_text,
            "ai_reply": ai_reply,
            "audio_url": audio_url
        })

    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

# =========================================================
# FILE AUDIO MP3
# =========================================================
@app.route("/static/<path:filename>")
def serve_audio(filename):
    return send_from_directory(AUDIO_DIR, filename)

# =========================================================
# RUN SERVER
# =========================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
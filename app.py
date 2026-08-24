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
# API KEY DARI ENVIRONMENT VARIABLE (Hanya Groq)
# =========================================================
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

if not GROQ_API_KEY:
    print("PERINGATAN: GROQ_API_KEY belum diatur!")

# =========================================================
# GROQ CLIENT (Whisper & Llama)
# =========================================================
groq_client = None
if GROQ_API_KEY:
    groq_client = Groq(api_key=GROQ_API_KEY)

# =========================================================
# FUNGSI TTS (Suara Anak Perempuan Ceria - Edge-TTS)
# =========================================================
async def generate_edge_tts(text, output_path):
    voice = "id-ID-GadisNeural"
    communicate = edge_tts.Communicate(text, voice, rate="+10%", pitch="+15Hz")
    await communicate.save(output_path)

# =========================================================
# HALAMAN UTAMA (Langsung Buka index.html Sejajar app.py)
# =========================================================
@app.route("/")
def home():
    return send_from_directory('.', 'index.html')

# =========================================================
# VOICE CHAT (Untuk HP & ESP32)
# =========================================================
@app.route("/voice-chat", methods=["POST"])
def voice_chat():
    try:
        if groq_client is None:
            return jsonify({"status": "error", "error": "GROQ_API_KEY belum diatur di server"}), 500

        wav_data = request.data
        if not wav_data or len(wav_data) < 44:
            return jsonify({"status": "error", "error": "Audio WAV tidak valid"}), 400

        print("\n========================================")
        print("AUDIO DITERIMA DARI ESP32 / HP")
        print("Ukuran:", len(wav_data), "bytes")
        print("========================================")

        # Simpan file WAV sementara
        input_filename = "input_" + str(uuid.uuid4()) + ".wav"
        input_path = os.path.join(AUDIO_DIR, input_filename)
        with open(input_path, "wb") as f:
            f.write(wav_data)

        # 1. Transcribe dengan Groq Whisper
        print("Memproses suara dengan Groq Whisper...")
        with open(input_path, "rb") as audio_file:
            transcript = groq_client.audio.transcriptions.create(
                model="whisper-large-v3-turbo",
                file=audio_file,
                language="id"
            )

        user_text = transcript.text.strip()
        print("\nPENGGUNA:", user_text)

        if not user_text:
            return jsonify({"status": "error", "error": "Suara tidak terdeteksi"}), 400

        # 2. Chat AI dengan Groq Llama (Diperbarui)
        print("Mengirim pertanyaan ke Groq Llama...")
        chat_completion = groq_client.chat.completions.create(
            messages=[
                {
                    "role": "system", 
                    "content": "Kamu adalah robot anak perempuan yang ceria, lucu, dan ramah untuk anak-anak. Gunakan bahasa Indonesia santai. Maksimal 2 kalimat pendek."
                },
                {"role": "user", "content": user_text}
            ],
            model="llama3-8b-8192",
        )
        ai_reply = chat_completion.choices[0].message.content.strip()
        print("\nAI:", ai_reply)

        if not ai_reply:
            return jsonify({"status": "error", "error": "Groq tidak memberikan jawaban"}), 500

        # 3. Text to Speech (Edge-TTS Suara Anak Perempuan)
        output_filename = "response_" + str(uuid.uuid4()) + ".mp3"
        output_path = os.path.join(AUDIO_DIR, output_filename)

        print("Membuat suara anak perempuan (Edge-TTS)...")
        asyncio.run(generate_edge_tts(ai_reply, output_path))

        audio_url = request.host_url.rstrip("/") + "/static/" + output_filename
        print("\nAUDIO AI:", audio_url)

        return jsonify({
            "status": "success",
            "user_text": user_text,
            "ai_reply": ai_reply,
            "audio_url": audio_url
        })

    except Exception as e:
        print("\n========================================")
        print("ERROR:", str(e))
        print("========================================")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/static/<path:filename>")
def serve_audio(filename):
    return send_from_directory(AUDIO_DIR, filename)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
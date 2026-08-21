from flask import Flask, request, jsonify, send_from_directory
import os
import uuid
import asyncio
import edge_tts
from groq import Groq
import google.generativeai as genai

app = Flask(__name__)
AUDIO_DIR = "static"
os.makedirs(AUDIO_DIR, exist_ok=True)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-3.6-flash")
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Fungsi Edge-TTS (Suara Anak Perempuan Ceria)
async def generate_audio(text, output_path):
    # GadisNeural adalah suara remaja/anak perempuan yang paling ceria
    voice = "id-ID-GadisNeural"
    communicate = edge_tts.Communicate(text, voice, rate="+20%", pitch="+20Hz")
    await communicate.save(output_path)

@app.route("/")
def home():
    return send_from_directory(".", "index.html")

@app.route("/voice-chat", methods=["POST"])
def voice_chat():
    try:
        wav_data = request.data
        input_filename = f"input_{uuid.uuid4()}.wav"
        input_path = os.path.join(AUDIO_DIR, input_filename)
        with open(input_path, "wb") as f: f.write(wav_data)

        # STT
        with open(input_path, "rb") as f:
            transcript = groq_client.audio.transcriptions.create(model="whisper-large-v3-turbo", file=f, language="id")
        user_text = transcript.text.strip()

        # AI Response
        prompt = f"Kamu adalah robot anak perempuan yang sangat ceria dan lucu. Jawab singkat maksimal 2 kalimat. Pertanyaan: {user_text}"
        response = model.generate_content(prompt)
        ai_reply = response.text.strip()

        # TTS (Edge-TTS)
        output_filename = f"response_{uuid.uuid4()}.mp3"
        output_path = os.path.join(AUDIO_DIR, output_filename)
        asyncio.run(generate_audio(ai_reply, output_path))

        return jsonify({
            "status": "success",
            "user_text": user_text,
            "ai_reply": ai_reply,
            "audio_url": request.host_url.rstrip("/") + "/static/" + output_filename
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/static/<path:filename>")
def serve_audio(filename):
    return send_from_directory(AUDIO_DIR, filename)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
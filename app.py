from flask import Flask, request, jsonify, render_template_string, send_from_directory, abort
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
                return False, f"Durasi audio terlalu panjang. Maksimal {MAX_AUDIO_SECONDS} detik."

            return True, None
    except Exception as e:
        return False, f"Gagal membaca WAV: {str(e)}"

# =========================================================
# EDGE TTS
# =========================================================

async def generate_edge_tts(text, output_path):
    voice = "id-ID-GadisNeural"
    communicate = edge_tts.Communicate(text=text, voice=voice, rate="+10%", pitch="+15Hz")
    await communicate.save(output_path)

def run_tts(text, output_path):
    asyncio.run(generate_edge_tts(text, output_path))

# =========================================================
# HOME (WEB INTERFACE & API INFO)
# =========================================================

@app.route("/")
def home():
    # Jika diakses dari browser, tampilkan halaman web interaktif
    # Jika diakses script/ESP32 dengan Header Accept: application/json, berikan respon JSON
    if "text/html" in request.headers.get("Accept", ""):
        html_template = """
        <!DOCTYPE html>
        <html lang="id">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Mainan AI Voice Chat</title>
            <style>
                body { font-family: Arial, sans-serif; background: #f0f2f5; margin: 0; padding: 20px; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; }
                .card { background: white; padding: 25px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); width: 100%; max-width: 400px; text-align: center; }
                button { background: #007bff; color: white; border: none; padding: 14px 20px; border-radius: 8px; font-size: 16px; cursor: pointer; margin-top: 15px; width: 100%; font-weight: bold; }
                button:active { background: #0056b3; }
                button.recording { background: #dc3545; }
                #status { margin-top: 15px; font-weight: bold; color: #555; font-size: 14px; }
                .chat-box { margin-top: 20px; text-align: left; max-height: 220px; overflow-y: auto; font-size: 14px; background: #f8f9fa; padding: 12px; border-radius: 8px; border: 1px solid #ddd; }
                .chat-msg { margin-bottom: 8px; line-height: 1.4; }
                .user-text { color: #007bff; }
                .ai-text { color: #28a745; }
            </style>
        </head>
        <body>
            <div class="card">
                <h2>🤖 Mainan AI Server</h2>
                <p>Tekan tombol untuk berbicara dengan AI!</p>
                <button id="recordBtn" onclick="toggleRecord()">🎤 Tekan untuk Bicara</button>
                <p id="status">Status: Siap</p>
                <div class="chat-box" id="chatBox">
                    <div class="chat-msg"><i>Belum ada percakapan...</i></div>
                </div>
            </div>

            <script>
                let mediaRecorder;
                let audioChunks = [];
                let isRecording = false;

                async function toggleRecord() {
                    const btn = document.getElementById("recordBtn");
                    const status = document.getElementById("status");

                    if (!isRecording) {
                        try {
                            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                            mediaRecorder = new MediaRecorder(stream);
                            audioChunks = [];

                            mediaRecorder.ondataavailable = event => {
                                audioChunks.push(event.data);
                            };

                            mediaRecorder.onstop = async () => {
                                status.innerText = "Memproses suara ke AI...";
                                const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });

                                try {
                                    const response = await fetch('/voice-chat', {
                                        method: 'POST',
                                        headers: { 'Content-Type': 'audio/wav' },
                                        body: audioBlob
                                    });
                                    const result = await response.json();

                                    if (result.status === "success") {
                                        status.innerText = "Selesai!";
                                        const chatBox = document.getElementById("chatBox");
                                        if (chatBox.innerHTML.includes("Belum ada percakapan")) chatBox.innerHTML = "";
                                        
                                        chatBox.innerHTML += `<div class="chat-msg user-text"><b>Kamu:</b> ${result.user_text}</div>`;
                                        chatBox.innerHTML += `<div class="chat-msg ai-text"><b>AI:</b> ${result.ai_reply}</div>`;
                                        chatBox.scrollTop = chatBox.scrollHeight;
                                        
                                        // Putar Suara Balasan AI
                                        const audio = new Audio(result.audio_url);
                                        audio.play();
                                    } else {
                                        status.innerText = "Error: " + result.error;
                                    }
                                } catch (err) {
                                    status.innerText = "Gagal terhubung ke server!";
                                    console.error(err);
                                }
                                btn.innerText = "🎤 Tekan untuk Bicara";
                                btn.classList.remove("recording");
                                isRecording = false;
                            };

                            mediaRecorder.start();
                            isRecording = true;
                            btn.innerText = "⏹️ Berhenti & Kirim";
                            btn.classList.add("recording");
                            status.innerText = "Merekam suara... Silakan bicara.";
                        } catch (err) {
                            alert("Gagal mengakses mikrofon! Pastikan izin mikrofon diaktifkan.");
                        }
                    } else {
                        mediaRecorder.stop();
                    }
                }
            </script>
        </body>
        </html>
        """
        return render_template_string(html_template)
    
    # Respon default untuk ESP32 atau API Tester
    return jsonify({
        "status": "online",
        "server": "Mainan AI Server Vercel",
        "version": "production",
        "message": "Server aktif dan siap menerima request dari Web maupun ESP32"
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
# VOICE CHAT (UNTUK WEB & ESP32)
# =========================================================

@app.route("/voice-chat", methods=["POST"])
def voice_chat():
    input_path = None
    output_path = None
    request_id = str(uuid.uuid4())
    start_time = time.time()

    try:
        cleanup_old_files()

        if groq_client is None:
            return jsonify({"status": "error", "error": "GROQ_API_KEY belum diatur"}), 500

        wav_data = request.get_data(cache=False)
        if not wav_data or len(wav_data) < 44:
            return jsonify({"status": "error", "error": "Data audio kosong atau tidak valid"}), 400

        if len(wav_data) > MAX_UPLOAD_SIZE:
            return jsonify({"status": "error", "error": "Ukuran audio melebihi batas 3 MB"}), 413

        # Simpan sementara
        input_filename = f"input_{request_id}.wav"
        input_path = os.path.join(AUDIO_DIR, input_filename)

        with open(input_path, "wb") as f:
            f.write(wav_data)

        # Validasi WAV
        valid_wav, wav_error = validate_wav(input_path)
        if not valid_wav:
            return jsonify({"status": "error", "error": wav_error}), 400

        # 1. Groq Whisper (STT)
        with open(input_path, "rb") as audio_file:
            transcript = groq_client.audio.transcriptions.create(
                model="whisper-large-v3-turbo",
                file=audio_file,
                language="id"
            )
        user_text = transcript.text.strip()

        if not user_text:
            return jsonify({"status": "error", "error": "Suara tidak terdeteksi"}), 400

        # 2. Groq Llama (AI Chat)
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
                {"role": "user", "content": user_text}
            ],
            temperature=0.7,
            max_tokens=MAX_TOKENS
        )
        ai_reply = chat_completion.choices[0].message.content.strip()

        if not ai_reply:
            return jsonify({"status": "error", "error": "AI tidak merespon"}), 500

        # 3. Edge TTS (Text to Speech)
        output_filename = f"response_{request_id}.mp3"
        output_path = os.path.join(AUDIO_DIR, output_filename)
        run_tts(ai_reply, output_path)

        if not os.path.exists(output_path) or os.path.getsize(output_path) <= 0:
            return jsonify({"status": "error", "error": "Gagal menghasilkan file audio TTS"}), 500

        output_size = os.path.getsize(output_path)
        audio_url = request.host_url.rstrip("/") + "/static/" + output_filename
        total_time = time.time() - start_time

        # Hapus file input WAV sementara
        if input_path and os.path.exists(input_path):
            os.remove(input_path)
            input_path = None

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
        return jsonify({"status": "error", "request_id": request_id, "error": str(e)}), 500

    finally:
        if input_path and os.path.exists(input_path):
            try:
                os.remove(input_path)
            except:
                pass

# =========================================================
# DOWNLOAD / STREAM MP3
# =========================================================

@app.route("/static/<path:filename>", methods=["GET"])
def serve_audio(filename):
    if not filename.startswith("response_") or not filename.endswith(".mp3"):
        abort(404)
    file_path = os.path.join(AUDIO_DIR, filename)
    if not os.path.isfile(file_path):
        abort(404)
    return send_from_directory(AUDIO_DIR, filename)

# =========================================================
# START SERVER LOKAL (JIKA DIJALANKAN DI PC)
# =========================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
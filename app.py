from flask import Flask, request, jsonify, render_template_string
import os
import time
from groq import Groq

# =========================================================
# FLASK
# =========================================================

app = Flask(__name__)

# =========================================================
# GROQ
# =========================================================

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

groq_client = None
if GROQ_API_KEY:
    groq_client = Groq(api_key=GROQ_API_KEY)

# =========================================================
# HOME (WEB INTERFACE & API INFO)
# =========================================================

@app.route("/")
def home():
    # Jika diakses dari browser HP, tampilkan halaman web chat dengan suara bawaan browser
    if "text/html" in request.headers.get("Accept", ""):
        html_template = """
        <!DOCTYPE html>
        <html lang="id">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Mainan AI Vercel</title>
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
                <h2>🤖 Mainan AI Vercel</h2>
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

                // Fungsi untuk membuat browser ngomong (TTS bawaan HP)
                function speakText(text) {
                    if ('speechSynthesis' in window) {
                        const utterance = new SpeechSynthesisUtterance(text);
                        utterance.lang = 'id-ID'; // Bahasa Indonesia
                        utterance.rate = 1.0;     // Kecepatan
                        window.speechSynthesis.speak(utterance);
                    }
                }

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
                                        
                                        // HP langsung membacakan jawaban AI secara otomatis!
                                        speakText(result.ai_reply);
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
                            alert("Gagal mengakses mikrofon! Pastikan izin mikrofon diaktifkan di browser.");
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
    
    return jsonify({
        "status": "online",
        "server": "Mainan AI Server Vercel",
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
# VOICE CHAT (UNTUK WEB & ESP32)
# =========================================================

@app.route("/voice-chat", methods=["POST"])
def voice_chat():
    try:
        if groq_client is None:
            return jsonify({"status": "error", "error": "GROQ_API_KEY belum diatur"}), 500

        wav_data = request.get_data(cache=False)
        if not wav_data or len(wav_data) < 44:
            return jsonify({"status": "error", "error": "Data audio kosong atau tidak valid"}), 400

        # Simpan sementara di folder tmp Vercel
        input_path = "/tmp/input_audio.wav"
        with open(input_path, "wb") as f:
            f.write(wav_data)

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

        # 2. Groq Llama (AI Chat) - Menggunakan model yang aktif saat ini
        chat_completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
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
            max_tokens=100
        )
        ai_reply = chat_completion.choices[0].message.content.strip()

        if not ai_reply:
            return jsonify({"status": "error", "error": "AI tidak merespon"}), 500

        return jsonify({
            "status": "success",
            "user_text": user_text,
            "ai_reply": ai_reply
        })

    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500
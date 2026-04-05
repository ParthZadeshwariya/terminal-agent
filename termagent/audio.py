import sounddevice as sd
import scipy.io.wavfile as wav
import tempfile
import os
import numpy as np

SAMPLE_RATE = 16000  # Whisper prefers 16kHz

_recording = False
_frames = []
_stream = None

def start_recording():
    global _recording, _frames, _stream
    _frames = []
    _recording = True

    def callback(indata, frames, time, status):
        if _recording:
            _frames.append(indata.copy())

    _stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='int16', callback=callback)
    _stream.start()

def stop_recording() -> str:
    """Stop recording and save to a temp .wav file. Returns the file path."""
    global _recording, _stream
    _recording = False
    if _stream:
        _stream.stop()
        _stream.close()
        _stream = None

    if not _frames:
        return ""

    audio = np.concatenate(_frames, axis=0)
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    wav.write(tmp.name, SAMPLE_RATE, audio)
    return tmp.name

from groq import Groq
import os

def transcribe(filepath: str) -> str:
    """Send a .wav file to Groq Whisper and return the transcribed text."""
    if not filepath or not os.path.exists(filepath):
        return ""

    try:
        client = Groq(api_key=os.getenv("GROQ_API_KEY"))

        with open(filepath, "rb") as f:
            result = client.audio.transcriptions.create(
                file=(os.path.basename(filepath), f),
                model="whisper-large-v3-turbo",
                response_format="text",
                language="en"
            )

        return result.strip() if isinstance(result, str) else result.text.strip()

    except Exception as e:
        return f"Transcription error: {str(e)}"

    finally:
        # Clean up the temp file
        try:
            os.remove(filepath)
        except Exception:
            pass
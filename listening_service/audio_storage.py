import wave
import os
import datetime
import threading
import numpy as np
import sys

from config import settings # Import the settings instance

class AudioStorageService:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(AudioStorageService, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            try:
                os.makedirs(settings.OUTPUT_DIR, exist_ok=True)
            except OSError as e:
                 print(f"Error creating output directory '{settings.OUTPUT_DIR}': {e}", file=sys.stderr)
                 # Depending on the desired behavior, you might want to exit or raise here.
                 # For now, just printing the error.

            self._initialized = True
            print("AudioStorageService initialized.")

    def save_recording(self, frames, start_time, end_time):
        """Saves the recorded frames to a WAV file."""
        if not start_time or not frames:
            print("No recording data to save.")
            return

        filename = f"{settings.OUTPUT_DIR}/{start_time.strftime('%Y%m%d_%H%M%S')}_to_{end_time.strftime('%H%M%S')}.wav"

        try:
            wf = wave.open(filename, 'wb')
            wf.setnchannels(settings.CHANNELS)
            wf.setsampwidth(np.dtype(settings.DTYPE).itemsize) # DTYPE is a numpy type from settings
            wf.setframerate(settings.SAMPLE_RATE)
            wf.writeframes(b''.join(frames))
            wf.close()
            print(f"Saved: {filename}")
        except Exception as e:
            print(f"Error saving file {filename}: {e}", file=sys.stderr)

# Singleton instance
audio_storage_service = AudioStorageService() 
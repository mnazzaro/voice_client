import wave
import os
import datetime
import threading
import numpy as np
import sys
import gzip
import shutil

from config import settings

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
        """Saves the recorded frames to a compressed WAV file (.wav.gz)."""
        if not start_time or not frames:
            print("No recording data to save.")
            return

        # Generate base filename (without extension)
        base_filename = f"{start_time.strftime('%Y%m%d_%H%M%S')}_to_{end_time.strftime('%H%M%S')}"
        wav_filename = f"{settings.OUTPUT_DIR}/{base_filename}.wav"
        gz_filename = f"{settings.OUTPUT_DIR}/{base_filename}.wav.gz"

        try:
            # 1. Write the uncompressed WAV file temporarily
            with wave.open(wav_filename, 'wb') as wf:
                wf.setnchannels(settings.CHANNELS)
                wf.setsampwidth(np.dtype(settings.DTYPE).itemsize)
                wf.setframerate(settings.SAMPLE_RATE)
                wf.writeframes(b''.join(frames))

            # 2. Compress the WAV file using gzip
            with open(wav_filename, 'rb') as f_in:
                with gzip.open(gz_filename, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)

            # 3. Remove the temporary uncompressed WAV file
            os.remove(wav_filename)

            print(f"Saved compressed: {gz_filename}")

        except wave.Error as e:
            print(f"Error writing temporary WAV file {wav_filename}: {e}", file=sys.stderr)
            # Clean up partial files if they exist
            if os.path.exists(wav_filename): os.remove(wav_filename)
            if os.path.exists(gz_filename): os.remove(gz_filename)
        except OSError as e:
            print(f"Error during file operation (compress/delete) for {base_filename}: {e}", file=sys.stderr)
            # Clean up partial files
            if os.path.exists(wav_filename): os.remove(wav_filename)
            if os.path.exists(gz_filename): os.remove(gz_filename)
        except Exception as e:
            print(f"Unexpected error saving file {gz_filename}: {e}", file=sys.stderr)
            # Clean up partial files
            if os.path.exists(wav_filename): os.remove(wav_filename)
            if os.path.exists(gz_filename): os.remove(gz_filename)

# Singleton instance
audio_storage_service = AudioStorageService() 
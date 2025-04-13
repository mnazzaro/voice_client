import sounddevice as sd
import numpy as np
import queue
import sys
import threading

from config import settings # Import the settings instance

class AudioInputService:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                # Double-check locking
                if cls._instance is None:
                    cls._instance = super(AudioInputService, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self.frames_queue = queue.Queue()
            self._stream = None
            self._stop_event = threading.Event()
            self._thread = None
            self._initialized = True
            print("AudioInputService initialized.")

    def _audio_callback(self, indata, frame_count, time_info, status):
        if status:
            print(f"Audio Callback Status: {status}", file=sys.stderr)
        # Ensure data is in the correct format (bytes of int16)
        if indata.dtype == np.float32:
             # Assuming the input range is [-1.0, 1.0] for float32
             indata_int16 = (indata * 32767).astype(settings.DTYPE)
        elif indata.dtype == settings.DTYPE:
             indata_int16 = indata
        else:
             print(f"Warning: Unexpected audio input dtype {indata.dtype}. Attempting conversion.", file=sys.stderr)
             # Attempt conversion, might fail or be incorrect
             indata_int16 = indata.astype(settings.DTYPE)

        self.frames_queue.put(indata_int16.tobytes())

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            print("Audio input service already running.")
            return

        print("Starting audio input service...")
        self._stop_event.clear()
        try:
            self._stream = sd.InputStream(
                samplerate=settings.SAMPLE_RATE,
                blocksize=settings.CHUNK_SIZE,
                channels=settings.CHANNELS,
                dtype=settings.DTYPE,
                callback=self._audio_callback
            )
            self._stream.start()
            print("Audio stream started.")
        except Exception as e:
            print(f"Error starting audio stream: {e}", file=sys.stderr)
            # Potentially re-raise or handle more gracefully
            raise

    def stop(self):
        print("Stopping audio input service...")
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
                print("Audio stream stopped and closed.")
            except Exception as e:
                print(f"Error stopping audio stream: {e}", file=sys.stderr)
            finally:
                self._stream = None
        # Signal the callback loop to exit if it were in a thread
        self._stop_event.set()
        # No separate thread managing the stream directly in this sd.InputStream model
        # The callback runs in sounddevice's thread context.

    def get_queue(self):
        return self.frames_queue

# Singleton instance
audio_input_service = AudioInputService() 
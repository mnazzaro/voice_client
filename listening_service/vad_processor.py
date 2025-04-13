import webrtcvad
import collections
import datetime
import threading
import queue
import sys

from config import settings # Import the settings instance
from audio_input import audio_input_service
from audio_storage import audio_storage_service

class VadProcessorService:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(VadProcessorService, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self.vad = webrtcvad.Vad(settings.VAD_AGGRESSIVENESS)
            self.input_queue = audio_input_service.get_queue()
            # Initialize deque with maxlen for pre-buffer
            self.recording_frames = collections.deque(maxlen=settings.PRE_BUFFER_SIZE)
            self.triggered = False
            self.start_time = None
            self.silent_chunks = 0
            self.max_silent_chunks = settings.MAX_SILENT_CHUNKS
            self._stop_event = threading.Event()
            self._processing_thread = None
            self._initialized = True
            print("VadProcessorService initialized.")

    def _process_audio(self):
        """Processes audio frames from the queue using VAD."""
        print("VAD processing thread started.")
        while not self._stop_event.is_set():
            try:
                frame = self.input_queue.get(timeout=0.1) # Wait briefly for a frame
            except queue.Empty:
                # If we are triggered and the queue is empty for too long, maybe save?
                # This is a fallback, primary stop is silence detection below
                if self.triggered and self.silent_chunks > self.max_silent_chunks * 2: # Heuristic
                     print("Input stream seems to have ended during speech. Saving...")
                     self._save_current_recording()
                     self._reset_state()
                continue # Continue waiting

            # Perform VAD check
            try:
                 is_speech = self.vad.is_speech(frame, settings.SAMPLE_RATE)
            except Exception as e:
                 # Handle potential errors from vad.is_speech if frame format is wrong
                 print(f"Error during VAD processing: {e}", file=sys.stderr)
                 # Depending on the error, you might want to skip this frame or stop
                 continue

            if not self.triggered:
                self.recording_frames.append(frame) # Keep filling pre-buffer deque
                if is_speech:
                    self.triggered = True
                    # --- FIX: Remove maxlen when triggered --- 
                    self.recording_frames.maxlen = None 
                    self.start_time = datetime.datetime.now() # Mark start time
                    self.silent_chunks = 0
                    print(f"Speech started at {self.start_time.strftime('%Y-%m-%d_%H-%M-%S')}")
                    # Pre-buffer frames are already in the deque
            else:
                # Already triggered, append frame to the now unlimited deque
                self.recording_frames.append(frame)
                if is_speech:
                    self.silent_chunks = 0 # Reset silence counter on speech
                else:
                    self.silent_chunks += 1
                    # Check if silence threshold is met
                    if self.silent_chunks > self.max_silent_chunks:
                        end_time = datetime.datetime.now()
                        print(f"Speech ended at {end_time.strftime('%Y-%m-%d_%H-%M-%S')}. Saving...")
                        self._save_current_recording(end_time)
                        self._reset_state()
        print("VAD processing thread stopped.")

    def _save_current_recording(self, end_time=None):
        """Internal helper to save the current buffer."""
        if not self.start_time or not self.recording_frames:
            return # Nothing to save

        # Use current time if end_time wasn't explicitly passed (e.g., on stop)
        final_end_time = end_time or datetime.datetime.now()
        # Pass a list copy to the storage service
        audio_storage_service.save_recording(list(self.recording_frames), self.start_time, final_end_time)

    def _reset_state(self):
        """Resets the recording state after saving or stopping."""
        self.triggered = False
        self.start_time = None
        self.silent_chunks = 0
        # --- FIX: Clear deque and restore maxlen for next pre-buffer --- 
        self.recording_frames.clear()
        self.recording_frames.maxlen = settings.PRE_BUFFER_SIZE
        print(f"Resetting VAD state. Listening... (Max pre-buffer: {settings.PRE_BUFFER_DURATION_MS}ms)")

    def start(self):
        if self._processing_thread is not None and self._processing_thread.is_alive():
            print("VAD processing service already running.")
            return

        print("Starting VAD processing service...")
        self._stop_event.clear()
        self._processing_thread = threading.Thread(target=self._process_audio, daemon=True)
        self._processing_thread.start()

    def stop(self):
        print("Stopping VAD processing service...")
        self._stop_event.set() # Signal the processing loop to stop
        if self._processing_thread:
            self._processing_thread.join(timeout=2.0) # Wait for thread to finish
            if self._processing_thread.is_alive():
                print("Warning: VAD processing thread did not stop gracefully.", file=sys.stderr)

        # If currently triggered when stopped, save the last segment
        if self.triggered:
            print("Saving final segment...")
            self._save_current_recording()

        self._reset_state()
        self._processing_thread = None

# Singleton instance
vad_processor_service = VadProcessorService() 
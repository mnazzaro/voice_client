import webrtcvad
import collections
import datetime
import threading
import queue
import sys
import numpy as np
import noisereduce as nr # Import noisereduce

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
            # Deque for pre-buffer ONLY
            self.pre_buffer_frames = collections.deque(maxlen=settings.PRE_BUFFER_SIZE)
            # List to store the actual recording once triggered
            self.current_recording = []
            self.triggered = False
            self.start_time = None
            self.silent_chunks = 0
            self.max_silent_chunks = settings.MAX_SILENT_CHUNKS
            self._stop_event = threading.Event()
            self._processing_thread = None
            self.noise_clip = None # Store the learned noise clip
            self._initialized = True
            print("VadProcessorService initialized.")

    def learn_noise_profile(self, noise_audio_np: np.ndarray):
        """Learns the noise profile from a sample numpy array."""
        if noise_audio_np is None or noise_audio_np.size == 0:
             print("Warning: Empty audio provided for noise learning.", file=sys.stderr)
             self.noise_clip = None
             return
        print(f"Learning noise profile from {noise_audio_np.shape} audio sample...")
        # Store the noise clip itself. noisereduce uses it directly.
        # Ensure it's the correct dtype for noisereduce (float)
        if noise_audio_np.dtype != np.float32:
             noise_audio_float = noise_audio_np.astype(np.float32) / 32768.0 # Assuming int16 input
        else:
             noise_audio_float = noise_audio_np
        self.noise_clip = noise_audio_float
        print("Noise profile learned.")

    def _process_audio(self):
        """Processes audio frames from the queue using VAD and noise reduction."""
        print("VAD processing thread started.")
        while not self._stop_event.is_set():
            try:
                frame = self.input_queue.get(timeout=0.1) # Get frame (bytes)
            except queue.Empty:
                if self.triggered and self.silent_chunks > self.max_silent_chunks * 2:
                     print("Input stream seems to have ended during speech. Saving...")
                     self._save_current_recording()
                     self._reset_state()
                continue

            # Convert frame bytes to numpy array for processing
            audio_chunk_np = np.frombuffer(frame, dtype=settings.DTYPE)

            # --- Apply Noise Reduction --- 
            reduced_chunk_np = audio_chunk_np # Default to original if no profile
            if self.noise_clip is not None:
                # Convert chunk to float for noisereduce
                audio_chunk_float = audio_chunk_np.astype(np.float32) / 32768.0
                try:
                    # Apply noise reduction
                    reduced_chunk_float = nr.reduce_noise(y=audio_chunk_float,
                                                        sr=settings.SAMPLE_RATE,
                                                        y_noise=self.noise_clip,
                                                        prop_decrease=0.5, # Aggressiveness of reduction
                                                        n_fft=512, # Smaller FFT for lower latency
                                                        hop_length=128,
                                                        stationary=True # Assume hum is stationary
                                                        )
                    # Convert back to original dtype (int16)
                    reduced_chunk_np = (reduced_chunk_float * 32768.0).astype(settings.DTYPE)
                except Exception as nr_error:
                    print(f"Error during noise reduction: {nr_error}", file=sys.stderr)
                    # Fallback to original chunk if reduction fails
                    reduced_chunk_np = audio_chunk_np
            
            # Convert potentially reduced chunk back to bytes for VAD and storage
            reduced_frame_bytes = reduced_chunk_np.tobytes()
            # --------------------------- 

            # Perform VAD check on the reduced audio
            try:
                 is_speech = self.vad.is_speech(reduced_frame_bytes, settings.SAMPLE_RATE)
            except Exception as e:
                 print(f"Error during VAD processing: {e}", file=sys.stderr)
                 continue

            # --- Store the REDUCED frame --- 
            frame_to_store = reduced_frame_bytes
            # ------------------------------ 

            if not self.triggered:
                self.pre_buffer_frames.append(frame_to_store)
                if is_speech:
                    self.triggered = True
                    self.current_recording = list(self.pre_buffer_frames)
                    est_start_offset_ms = len(self.current_recording) * settings.CHUNK_DURATION_MS
                    self.start_time = datetime.datetime.now() - datetime.timedelta(milliseconds=est_start_offset_ms)
                    self.silent_chunks = 0
                    print(f"Speech started around {self.start_time.strftime('%Y-%m-%d_%H-%M-%S')}")
            else:
                self.current_recording.append(frame_to_store)
                if is_speech:
                    self.silent_chunks = 0
                else:
                    self.silent_chunks += 1
                    if self.silent_chunks > self.max_silent_chunks:
                        est_end_offset_ms = self.silent_chunks * settings.CHUNK_DURATION_MS
                        end_time = datetime.datetime.now() - datetime.timedelta(milliseconds=est_end_offset_ms)
                        print(f"Speech ended around {end_time.strftime('%Y-%m-%d_%H-%M-%S')}. Saving...")
                        self._save_current_recording(end_time)
                        self._reset_state()
        print("VAD processing thread stopped.")

    def _save_current_recording(self, end_time=None):
        """Internal helper to save the current recording list."""
        if not self.start_time or not self.current_recording:
            print("Save called but no data in current_recording.")
            return

        final_end_time = end_time or datetime.datetime.now()
        audio_storage_service.save_recording(self.current_recording, self.start_time, final_end_time)

    def _reset_state(self):
        """Resets the recording state after saving or stopping."""
        self.triggered = False
        self.start_time = None
        self.silent_chunks = 0
        self.current_recording = []
        # Don't clear pre-buffer here, it's rolling
        print(f"Resetting VAD state. Listening... (Pre-buffer: {settings.PRE_BUFFER_DURATION_MS}ms)")

    def start(self):
        if self._processing_thread is not None and self._processing_thread.is_alive():
            print("VAD processing service already running.")
            return
        # Ensure noise profile is learned before starting the processing thread
        if self.noise_clip is None:
             print("Warning: Starting VAD processor without a learned noise profile.", file=sys.stderr)
        
        print("Starting VAD processing service...")
        self._stop_event.clear()
        self._reset_state() # Reset trigger state
        self.pre_buffer_frames.clear() # Clear pre-buffer on full start
        self._processing_thread = threading.Thread(target=self._process_audio, daemon=True)
        self._processing_thread.start()

    def stop(self):
        print("Stopping VAD processing service...")
        self._stop_event.set()
        if self._processing_thread:
            self._processing_thread.join(timeout=2.0)
            if self._processing_thread.is_alive():
                print("Warning: VAD processing thread did not stop gracefully.", file=sys.stderr)

        if self.triggered:
            print("Saving final segment...")
            self._save_current_recording()

        self._reset_state()
        self._processing_thread = None
        # Optionally clear noise profile on stop?
        # self.noise_clip = None 

# Singleton instance
vad_processor_service = VadProcessorService() 
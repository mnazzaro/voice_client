import threading
import queue
import datetime
import sys
import math # For ceiling calculation if needed, though logic uses TARGET_CHUNKS_PER_FILE

from config import settings # Import the settings instance
from audio_input import audio_input_service
from audio_storage import audio_storage_service

class ChunkingProcessorService:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(ChunkingProcessorService, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self.input_queue = audio_input_service.get_queue()
            # List to store frames for the current chunk
            self.current_chunk_frames = []
            self.start_time = None
            self._stop_event = threading.Event()
            self._processing_thread = None
            self._initialized = True
            print("ChunkingProcessorService initialized.")

    def _process_audio(self):
        """Processes audio frames from the queue, chunking them by duration."""
        print("Chunking processing thread started.")
        while not self._stop_event.is_set():
            try:
                # Get frame with a timeout to allow checking stop_event
                frame = self.input_queue.get(timeout=0.1)

                # Record start time if this is the first frame of a new chunk
                if not self.start_time:
                    self.start_time = datetime.datetime.now()
                    # Adjust start time slightly back to account for the first chunk's duration?
                    # Or consider start time as the moment the *first* byte arrives for the chunk.
                    # Let's keep it simple: start_time = first frame arrival time.
                    print(f"Starting new chunk at {self.start_time.strftime('%Y-%m-%d_%H-%M-%S')}")

                self.current_chunk_frames.append(frame)

                # Check if the chunk has reached the target size
                if len(self.current_chunk_frames) >= settings.TARGET_CHUNKS_PER_FILE:
                    end_time = datetime.datetime.now()
                    print(f"Chunk complete at {end_time.strftime('%Y-%m-%d_%H-%M-%S')}. Saving...")
                    self._save_current_chunk(end_time)
                    self._reset_chunk_state() # Reset for the next chunk

            except queue.Empty:
                # Queue is empty, just continue waiting for frames
                # Check if we should save a partial chunk on timeout/stop? - Handled in stop()
                continue
            except Exception as e:
                 print(f"Error during chunk processing: {e}", file=sys.stderr)
                 # Decide if we should reset or try to continue
                 self._reset_chunk_state() # Reset state on error to avoid saving corrupted chunk

        print("Chunking processing thread stopped.")

    def _save_current_chunk(self, end_time):
        """Internal helper to save the current chunk list."""
        if not self.start_time or not self.current_chunk_frames:
            print("Save called but no data/start time for the current chunk.")
            return

        # Use the current_chunk_frames list
        # The audio_storage_service needs a list of byte frames
        audio_storage_service.save_recording(
            self.current_chunk_frames,
            self.start_time,
            end_time
        )

    def _reset_chunk_state(self):
        """Resets the state for the next chunk."""
        self.current_chunk_frames = []
        self.start_time = None
        print(f"Resetting chunk state. Waiting for next {settings.CHUNK_DURATION_MINUTES} minute chunk...")


    def start(self):
        if self._processing_thread is not None and self._processing_thread.is_alive():
            print("Chunking processing service already running.")
            return

        print("Starting Chunking processing service...")
        self._stop_event.clear()
        self._reset_chunk_state() # Ensure clean state on start
        self._processing_thread = threading.Thread(target=self._process_audio, daemon=True)
        self._processing_thread.start()

    def stop(self):
        print("Stopping Chunking processing service...")
        self._stop_event.set() # Signal the processing loop to stop
        if self._processing_thread:
            self._processing_thread.join(timeout=1.0) # Wait briefly for thread
            if self._processing_thread.is_alive():
                print("Warning: Chunking processing thread did not stop gracefully.", file=sys.stderr)

        # Save any remaining partial chunk when stopping
        if self.current_chunk_frames:
            print("Saving final partial chunk...")
            # Estimate end time if not naturally completed
            end_time = datetime.datetime.now()
            self._save_current_chunk(end_time)

        # Reset state after stopping and potentially saving
        self._reset_chunk_state()
        self._processing_thread = None
        print("ChunkingProcessorService stopped.")

# Singleton instance
chunking_processor_service = ChunkingProcessorService() 
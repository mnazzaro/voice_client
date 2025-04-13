import time
import signal
import sys
import numpy as np # Import numpy
import queue # Import queue for get()

# Import the singleton service instances and settings
from audio_input import audio_input_service
from vad_processor import vad_processor_service
from config import settings # Import the settings instance

running = True

def signal_handler(sig, frame):
    """Handles Ctrl+C interruption gracefully."""
    global running
    print('\nInterrupt received, shutting down services...')
    running = False

def capture_baseline_noise(duration_sec=2):
    """Captures audio for a short duration to establish a noise baseline."""
    print(f"Capturing {duration_sec} seconds of audio for noise baseline...")
    baseline_frames = []
    num_frames_to_capture = int(duration_sec * settings.SAMPLE_RATE / settings.CHUNK_SIZE)
    input_queue = audio_input_service.get_queue()

    # Ensure queue is clear before starting
    while not input_queue.empty():
        try: input_queue.get_nowait()
        except queue.Empty: break

    audio_input_service.start() # Start capturing
    time.sleep(0.2) # Allow stream to stabilize slightly

    frames_captured = 0
    capture_start_time = time.time()
    while frames_captured < num_frames_to_capture:
        try:
            frame = input_queue.get(timeout=0.5) # Wait for a frame
            baseline_frames.append(frame)
            frames_captured += 1
        except queue.Empty:
            print("Warning: Audio queue empty during baseline capture.")
            if time.time() - capture_start_time > duration_sec + 1: # Timeout safeguard
                 print("Error: Timeout waiting for baseline audio.", file=sys.stderr)
                 break # Avoid getting stuck
            continue
        except Exception as e:
             print(f"Error getting frame during baseline capture: {e}", file=sys.stderr)
             break # Exit loop on other errors

    audio_input_service.stop() # Stop capturing immediately after
    print(f"Captured {len(baseline_frames)} frames for baseline.")

    if not baseline_frames:
        return None

    # Combine frames and convert to numpy array
    baseline_data = b''.join(baseline_frames)
    baseline_np = np.frombuffer(baseline_data, dtype=settings.DTYPE)
    return baseline_np

def main():
    global running
    print("Starting application...")
    # Access settings via the imported object
    print(f"Configuration: Sample Rate={settings.SAMPLE_RATE}, Chunk={settings.CHUNK_DURATION_MS}ms, Output='{settings.OUTPUT_DIR}'")
    print(f"VAD: Aggressiveness={settings.VAD_AGGRESSIVENESS}, Silence Threshold={settings.SILENCE_THRESHOLD_MS}ms, Pre-buffer={settings.PRE_BUFFER_DURATION_MS}ms")

    # Setup signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # --- Learn Noise Profile --- 
        print("Please ensure ~2 seconds of silence for noise profile learning.")
        noise_sample = capture_baseline_noise(duration_sec=2)
        if noise_sample is not None:
            vad_processor_service.learn_noise_profile(noise_sample)
        else:
            print("Failed to capture baseline noise. Proceeding without noise reduction.")
        # -------------------------- 

        # Start the services
        audio_input_service.start()
        vad_processor_service.start()

        print(f"#{'='*30}")
        print(" Application running. Press Ctrl+C to stop.")
        print(f"#{'='*30}")

        # Keep the main thread alive
        while running:
            time.sleep(1) # Sleep to prevent busy-waiting

    except Exception as e:
        print(f"An unexpected error occurred in main: {e}", file=sys.stderr)
    finally:
        print("Initiating shutdown...")
        # Stop services in reverse order of dependency/start
        vad_processor_service.stop()
        audio_input_service.stop()
        print("Application shutdown complete.")

if __name__ == "__main__":
    main()

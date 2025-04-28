import time
import signal
import sys

# Import the singleton service instances and settings
from audio_input import audio_input_service
from chunking_processor import chunking_processor_service
from config import settings # Import the settings instance

running = True

def signal_handler(sig, frame):
    """Handles Ctrl+C interruption gracefully."""
    global running
    print('\nInterrupt received, shutting down services...')
    running = False

def main():
    global running
    print("Starting application...")
    # Access settings via the imported object
    print(f"Configuration: Sample Rate={settings.SAMPLE_RATE}, Chunk={settings.CHUNK_DURATION_MS}ms, Output='{settings.OUTPUT_DIR}', Save Chunk Minutes={settings.CHUNK_DURATION_MINUTES}")

    # Setup signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Start the services
        audio_input_service.start()
        chunking_processor_service.start()

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
        chunking_processor_service.stop()
        audio_input_service.stop()
        print("Application shutdown complete.")

if __name__ == "__main__":
    main()

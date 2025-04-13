import numpy as np
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, computed_field

class Settings(BaseSettings):
    # Load settings from a .env file
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')

    # --- Audio Configuration ---
    SAMPLE_RATE: int = Field(16000, description="Rate in Hz (must be 8000, 16000, 32000, or 48000 for VAD)")
    CHUNK_DURATION_MS: int = Field(30, description="Duration of audio chunks for VAD in ms (must be 10, 20, or 30)")
    CHANNELS: int = Field(1, description="Number of audio channels")
    # DTYPE is derived, not directly loaded

    # --- VAD Configuration ---
    VAD_AGGRESSIVENESS: int = Field(0, ge=0, le=3, description="VAD aggressiveness mode (0=least, 3=most aggressive)")
    SILENCE_THRESHOLD_MS: int = Field(2000, description="How long silence must last to end a segment (ms)")
    PRE_BUFFER_DURATION_MS: int = Field(300, description="How much audio to keep before speech starts (ms)")

    # --- Output Configuration ---
    OUTPUT_DIR: str = Field("recordings", description="Directory to save recordings")

    # --- Computed Fields ---
    @computed_field
    @property
    def CHUNK_SIZE(self) -> int:
        "Size of each audio chunk in frames."
        return int(self.SAMPLE_RATE * self.CHUNK_DURATION_MS / 1000)

    @computed_field
    @property
    def DTYPE(self) -> np.dtype:
        "Numpy data type for recording (always int16 for VAD)."
        return np.int16

    @computed_field
    @property
    def MAX_SILENT_CHUNKS(self) -> int:
        "Number of silent chunks before triggering end of speech."
        return self.SILENCE_THRESHOLD_MS // self.CHUNK_DURATION_MS

    @computed_field
    @property
    def PRE_BUFFER_SIZE(self) -> int:
        "Size of the pre-buffer in chunks."
        return int(self.PRE_BUFFER_DURATION_MS / self.CHUNK_DURATION_MS)

# Create a single settings instance for the application to import
settings = Settings()

# --- Validation (Optional but Recommended) ---
def validate_settings():
    if settings.SAMPLE_RATE not in [8000, 16000, 32000, 48000]:
        raise ValueError("SAMPLE_RATE must be one of 8000, 16000, 32000, 48000")
    if settings.CHUNK_DURATION_MS not in [10, 20, 30]:
        raise ValueError("CHUNK_DURATION_MS must be one of 10, 20, 30")
    if settings.CHANNELS != 1:
        # Currently, VAD processing assumes mono
        print("Warning: CHANNELS is not 1. VAD processing assumes mono input.")

# Run validation when the module is imported
validate_settings() 
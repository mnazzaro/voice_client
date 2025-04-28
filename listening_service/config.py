import numpy as np
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, computed_field
import math # Added for ceiling calculation

class Settings(BaseSettings):
    # Load settings from a .env file
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')

    # --- Audio Configuration ---
    SAMPLE_RATE: int = Field(16000, description="Audio sample rate in Hz.")
    CHUNK_DURATION_MS: int = Field(30, description="Duration of audio chunks processed internally (ms).")
    CHANNELS: int = Field(1, description="Number of audio channels")
    # DTYPE is derived, not directly loaded

    # --- Recording Configuration ---
    CHUNK_DURATION_MINUTES: int = Field(5, description="Duration of each saved audio chunk in minutes.")

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
        "Numpy data type for recording."
        return np.int16

    @computed_field
    @property
    def TARGET_CHUNKS_PER_FILE(self) -> int:
        "Target number of internal chunks per output file."
        total_ms_per_file = self.CHUNK_DURATION_MINUTES * 60 * 1000
        # Use ceiling to ensure we capture the full duration
        return math.ceil(total_ms_per_file / self.CHUNK_DURATION_MS)



# Create a single settings instance for the application to import
settings = Settings()

# --- Validation (Optional but Recommended) ---
def validate_settings():
    if settings.CHUNK_DURATION_MS <= 0:
        raise ValueError("CHUNK_DURATION_MS must be positive.")
    if settings.CHUNK_DURATION_MINUTES <= 0:
        raise ValueError("CHUNK_DURATION_MINUTES must be positive.")

# Run validation when the module is imported
validate_settings() 
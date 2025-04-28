import os
import sys
import datetime
from pathlib import Path
from typing import List, Optional
import zipfile
import io
import wave
import gzip   # Added for compression/decompression
import shutil # Added for streaming compression

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# Add the listening_service directory to sys.path to import its config
SERVICE_DIR = Path(__file__).parent.parent / 'listening_service'
sys.path.append(str(SERVICE_DIR))

try:
    # Attempt to import the settings from the listening service
    # Ensure __init__.py exists in listening_service
    from listening_service.config import settings as listener_settings
except ImportError as e:
    print(f"Error importing listener settings: {e}", file=sys.stderr)
    print("Please ensure listening_service is in the Python path and has an __init__.py", file=sys.stderr)
    # Provide default/fallback settings if import fails
    class FallbackSettings:
        OUTPUT_DIR = "../recordings" # Relative guess
    listener_settings = FallbackSettings()

app = FastAPI()

# Use absolute path for templates based on this file's location
TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Resolve the absolute path for the recordings directory
RECORDINGS_DIR = Path(listener_settings.OUTPUT_DIR)
print(f"RECORDINGS_DIR: {listener_settings.OUTPUT_DIR}")
if not RECORDINGS_DIR.is_absolute():
    # Assume it's relative to the listening_service directory if not absolute
    RECORDINGS_DIR = (Path(__file__).parent.parent / listener_settings.OUTPUT_DIR).resolve()

print(f"UI Service using recordings directory: {RECORDINGS_DIR}")

class RecordingInfo(BaseModel):
    filename: str
    start_dt: datetime.datetime
    end_dt: datetime.datetime
    start_str: str
    end_str: str
    duration_sec: float
    filepath: Path

def parse_filename(filename: str, filepath: Path) -> Optional[RecordingInfo]:
    """Parses start/end datetime and calculates duration from filename (.wav.gz)."""
    # Expecting format like YYYYMMDD_HHMMSS_to_HHMMSS.wav.gz
    if not filename.endswith(".wav.gz"):
        return None
    base_filename = filename[:-len(".wav.gz")] # Remove .wav.gz
    parts = base_filename.split('_to_')
    if len(parts) == 2:
        start_part, end_part = parts
        try:
            start_dt = datetime.datetime.strptime(start_part, '%Y%m%d_%H%M%S')
            # Assume end time is on the same day unless it wraps past midnight
            end_dt = datetime.datetime.strptime(f"{start_dt.strftime('%Y%m%d')}_{end_part}", '%Y%m%d_%H%M%S')
            if end_dt < start_dt:
                 end_dt += datetime.timedelta(days=1)

            # Calculate duration
            duration = end_dt - start_dt
            duration_sec = round(duration.total_seconds(), 1)

            return RecordingInfo(
                filename=filename, # Keep original .wav.gz filename
                start_dt=start_dt,
                end_dt=end_dt,
                start_str=start_dt.strftime('%Y-%m-%d %H:%M:%S'),
                end_str=end_dt.strftime('%Y-%m-%d %H:%M:%S'),
                duration_sec=duration_sec,
                filepath=filepath
            )
        except ValueError:
            print(f"Error parsing filename: {filename}", file=sys.stderr)
            return None
    return None

def get_recordings(start_date: Optional[datetime.date] = None, end_date: Optional[datetime.date] = None) -> List[RecordingInfo]:
    """Gets list of recordings (.wav.gz), optionally filtered by date range."""
    recordings = []
    if not RECORDINGS_DIR.exists() or not RECORDINGS_DIR.is_dir():
        print(f"Warning: Recordings directory not found or not a directory: {RECORDINGS_DIR}")
        return []

    for item in RECORDINGS_DIR.iterdir():
        # Look for .wav.gz files
        if item.is_file() and item.name.endswith('.wav.gz'):
            info = parse_filename(item.name, item)
            if info:
                # Apply date filtering (inclusive)
                recording_date = info.start_dt.date()
                if start_date and recording_date < start_date:
                    continue
                if end_date and recording_date > end_date:
                    continue
                recordings.append(info)

    # Sort by start time, newest first
    recordings.sort(key=lambda r: r.start_dt, reverse=True)
    return recordings

def get_recordings_in_range(start_dt: datetime.datetime, end_dt: datetime.datetime) -> List[RecordingInfo]:
    """Gets list of recordings (.wav.gz) that overlap with the given datetime range."""
    recordings = []
    if not RECORDINGS_DIR.exists() or not RECORDINGS_DIR.is_dir():
        print(f"Warning: Recordings directory not found: {RECORDINGS_DIR}")
        return []

    for item in RECORDINGS_DIR.iterdir():
        # Look for .wav.gz files
        if item.is_file() and item.name.endswith('.wav.gz'):
            info = parse_filename(item.name, item)
            if info:
                # Check for overlap: (StartA <= EndB) and (EndA >= StartB)
                if info.start_dt <= end_dt and info.end_dt >= start_dt:
                    recordings.append(info)

    # Sort by start time, ASCENDING for concatenation
    recordings.sort(key=lambda r: r.start_dt, reverse=False)
    return recordings

def combine_wav_files(file_list: List[Path]) -> Optional[io.BytesIO]:
    """Decompresses and combines multiple WAV files (.wav.gz) into a single uncompressed WAV in memory."""
    if not file_list:
        return None

    output_buffer = io.BytesIO() # This will hold the uncompressed combined WAV data
    first_file = True
    params = None

    try:
        with wave.open(output_buffer, 'wb') as outfile:
            for filepath in file_list:
                if not filepath.exists() or not filepath.name.endswith('.wav.gz'):
                    print(f"Warning: File not found or not .wav.gz: {filepath}", file=sys.stderr)
                    continue

                try:
                    # Open the gzipped file and pass the file-like object to wave.open
                    with gzip.open(filepath, 'rb') as compressed_f:
                        with wave.open(compressed_f, 'rb') as infile:
                            current_params = infile.getparams()
                            if first_file:
                                params = current_params
                                outfile.setparams(params)
                                first_file = False
                            elif current_params != params:
                                print(f"Error: WAV file {filepath.name} has incompatible parameters.", file=sys.stderr)
                                print(f"Expected: {params}", file=sys.stderr)
                                print(f"Got: {current_params}", file=sys.stderr)
                                return None # Abort on incompatible parameters

                            # Read and write frame data
                            frames = infile.readframes(infile.getnframes())
                            outfile.writeframes(frames)
                except gzip.BadGzipFile:
                    print(f"Error: File is not a valid Gzip file: {filepath.name}", file=sys.stderr)
                    continue # Skip corrupted files
                except EOFError:
                    print(f"Error: Gzip file ended unexpectedly (possibly corrupt): {filepath.name}", file=sys.stderr)
                    continue # Skip corrupted files
                except wave.Error as e:
                    print(f"Error processing decompressed WAV data from {filepath.name}: {e}", file=sys.stderr)
                    return None # Abort if WAV content is bad

    except Exception as e:
        print(f"Unexpected error during WAV combination: {e}", file=sys.stderr)
        return None

    if first_file: # No valid files processed
        return None

    output_buffer.seek(0)
    return output_buffer # Return uncompressed combined data

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, start_date: Optional[str] = None, end_date: Optional[str] = None):
    """Serves the main UI page with recordings list."""
    s_date = None
    e_date = None
    try:
        if start_date:
            s_date = datetime.datetime.strptime(start_date, '%Y-%m-%d').date()
        if end_date:
            e_date = datetime.datetime.strptime(end_date, '%Y-%m-%d').date()
    except ValueError:
        # Handle invalid date format gracefully, maybe show an error or ignore
        pass # Or: raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    recordings_list = get_recordings(start_date=s_date, end_date=e_date)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "recordings": recordings_list,
            "start_date": start_date or "",
            "end_date": end_date or ""
        }
    )

@app.get("/download/{filename}")
async def download_recording(filename: str):
    """Serves a single compressed recording file (.wav.gz) for download."""
    if ".." in filename or "/" in filename or not filename.endswith(".wav.gz"):
        raise HTTPException(status_code=400, detail="Invalid filename.")

    file_path = RECORDINGS_DIR / filename
    if file_path.exists() and file_path.is_file():
        # Serve the compressed file directly
        return FileResponse(
            file_path,
            media_type='application/gzip', # Correct media type for gzip
            filename=filename
        )
    else:
        raise HTTPException(status_code=404, detail="File not found")

@app.get("/download_combined")
async def download_combined_wav(start_dt: str, end_dt: str):
    """Finds recordings (.wav.gz), decompresses, combines, recompresses, and streams the result."""
    try:
        start_datetime = datetime.datetime.fromisoformat(start_dt)
        end_datetime = datetime.datetime.fromisoformat(end_dt)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime format. Use ISO format (YYYY-MM-DDTHH:MM).")

    if start_datetime >= end_datetime:
        raise HTTPException(status_code=400, detail="Start datetime must be before end datetime.")

    print(f"Requesting combined compressed WAV from {start_datetime} to {end_datetime}")

    recordings_to_combine = get_recordings_in_range(start_datetime, end_datetime)

    if not recordings_to_combine:
        raise HTTPException(status_code=404, detail="No recordings found overlapping the specified time range.")

    print(f"Found {len(recordings_to_combine)} recordings to combine:")
    for rec in recordings_to_combine:
        print(f"  - {rec.filename}")

    # Decompress and combine into an uncompressed WAV buffer
    uncompressed_wav_buffer = combine_wav_files([rec.filepath for rec in recordings_to_combine])

    if uncompressed_wav_buffer is None:
        raise HTTPException(status_code=500, detail="Failed to combine WAV files. Check server logs for incompatible or corrupt files.")

    # Re-compress the combined buffer using gzip
    compressed_output_buffer = io.BytesIO()
    try:
        with gzip.open(compressed_output_buffer, 'wb') as f_out:
            shutil.copyfileobj(uncompressed_wav_buffer, f_out)
    except Exception as e:
        print(f"Error re-compressing combined WAV data: {e}", file=sys.stderr)
        raise HTTPException(status_code=500, detail="Failed to re-compress combined audio data.")
    finally:
        uncompressed_wav_buffer.close() # Clean up the intermediate buffer

    compressed_output_buffer.seek(0)

    # Create filename for the combined compressed download
    start_str = start_datetime.strftime('%Y%m%d_%H%M%S')
    end_str = end_datetime.strftime('%Y%m%d_%H%M%S')
    # Add .wav.gz extension to the final filename
    combined_filename = f"combined_recording_{start_str}_to_{end_str}.wav.gz"

    return StreamingResponse(
        compressed_output_buffer, # Stream the compressed data
        media_type="application/gzip", # Correct media type
        headers={"Content-Disposition": f"attachment; filename={combined_filename}"}
    )

@app.get("/download_all")
async def download_all_recordings(start_date: Optional[str] = None, end_date: Optional[str] = None):
    """Streams a ZIP file containing compressed recordings (.wav.gz) filtered by date range."""
    s_date = None
    e_date = None
    try:
        if start_date:
            s_date = datetime.datetime.strptime(start_date, '%Y-%m-%d').date()
        if end_date:
            e_date = datetime.datetime.strptime(end_date, '%Y-%m-%d').date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    # get_recordings now returns .wav.gz files
    recordings_list = get_recordings(start_date=s_date, end_date=e_date)

    if not recordings_list:
        raise HTTPException(status_code=404, detail="No recordings found for the selected date range.")

    zip_buffer = io.BytesIO()
    # Use ZIP_STORED if files are already compressed, or ZIP_DEFLATED for further zip compression
    # Let's use ZIP_DEFLATED for potentially better overall compression of the archive.
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for recording in recordings_list:
            if recording.filepath.exists():
                # Add the .wav.gz file to the zip archive
                zipf.write(recording.filepath, arcname=recording.filename)

    zip_buffer.seek(0)

    # Create a filename for the zip download
    zip_filename = f"recordings"
    if s_date:
        zip_filename += f"_from_{s_date.strftime('%Y%m%d')}"
    if e_date:
        zip_filename += f"_to_{e_date.strftime('%Y%m%d')}"
    zip_filename += ".zip"

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={zip_filename}"}
    )

# Basic entry point for running with uvicorn (for development)
if __name__ == "__main__":
    import uvicorn
    print(f"Starting Uvicorn server for UI...")
    print(f"Access at: http://127.0.0.1:8000")
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True, app_dir=str(Path(__file__).parent)) 
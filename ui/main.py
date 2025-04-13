import os
import sys
import datetime
from pathlib import Path
from typing import List, Optional
import zipfile
import io

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
    """Parses start/end datetime and calculates duration from filename."""
    parts = filename.replace(".wav", "").split('_to_')
    if len(parts) == 2:
        start_part, end_part = parts
        try:
            start_dt = datetime.datetime.strptime(start_part, '%Y%m%d_%H%M%S')
            end_dt = datetime.datetime.strptime(f"{start_dt.strftime('%Y%m%d')}_{end_part}", '%Y%m%d_%H%M%S')
            if end_dt < start_dt:
                 end_dt += datetime.timedelta(days=1)

            # Calculate duration
            duration = end_dt - start_dt
            duration_sec = round(duration.total_seconds(), 1) # Round to 1 decimal place

            return RecordingInfo(
                filename=filename,
                start_dt=start_dt,
                end_dt=end_dt,
                start_str=start_dt.strftime('%Y-%m-%d %H:%M:%S'),
                end_str=end_dt.strftime('%Y-%m-%d %H:%M:%S'),
                duration_sec=duration_sec,
                filepath=filepath
            )
        except ValueError:
            return None
    return None

def get_recordings(start_date: Optional[datetime.date] = None, end_date: Optional[datetime.date] = None) -> List[RecordingInfo]:
    """Gets list of recordings, optionally filtered by date range."""
    recordings = []
    if not RECORDINGS_DIR.exists() or not RECORDINGS_DIR.is_dir():
        print(f"Warning: Recordings directory not found or not a directory: {RECORDINGS_DIR}")
        return []

    for item in RECORDINGS_DIR.iterdir():
        if item.is_file() and item.suffix == '.wav':
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
    """Serves a single recording file for download."""
    # Basic security check: ensure filename doesn't contain path traversal chars
    if ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")

    file_path = RECORDINGS_DIR / filename
    if file_path.exists() and file_path.is_file():
        return FileResponse(file_path, media_type='audio/wav', filename=filename)
    else:
        raise HTTPException(status_code=404, detail="File not found")

@app.get("/download_all")
async def download_all_recordings(start_date: Optional[str] = None, end_date: Optional[str] = None):
    """Streams a ZIP file containing recordings filtered by date range."""
    s_date = None
    e_date = None
    try:
        if start_date:
            s_date = datetime.datetime.strptime(start_date, '%Y-%m-%d').date()
        if end_date:
            e_date = datetime.datetime.strptime(end_date, '%Y-%m-%d').date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    recordings_list = get_recordings(start_date=s_date, end_date=e_date)

    if not recordings_list:
        raise HTTPException(status_code=404, detail="No recordings found for the selected date range.")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for recording in recordings_list:
            if recording.filepath.exists():
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
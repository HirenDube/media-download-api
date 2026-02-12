from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from typing import Optional
from dotenv import load_dotenv
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import yt_dlp
import os
import re

# -----------------------------
# Load ENV
# -----------------------------
load_dotenv()

API_KEY = os.getenv("API_KEY")
RATE_LIMIT = os.getenv("RATE_LIMIT", "20/minute")

# -----------------------------
# Rate Limiter Setup
# -----------------------------
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Media Extract API",
    description="Advanced media extraction API using yt-dlp with filtering & rate limiting.",
    version="1.1.0"
)

app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Try again later."}
    )


# -----------------------------
# Utility Functions
# -----------------------------

def human_readable_size(size_bytes):
    if not size_bytes:
        return None
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} PB"


def parse_filesize_limit(size_str):
    if not size_str:
        return None

    size_str = size_str.upper().strip()
    match = re.match(r"(\d+)(MB|GB)", size_str)
    if not match:
        return None

    value = int(match.group(1))
    unit = match.group(2)

    if unit == "MB":
        return value * 1024 * 1024
    if unit == "GB":
        return value * 1024 * 1024 * 1024


def resolution_to_number(res):
    if not res:
        return None
    match = re.search(r"(\d+)", res)
    if match:
        return int(match.group(1))
    return None


# -----------------------------
# API Endpoint
# -----------------------------

@app.get("/extract")
@limiter.limit(RATE_LIMIT)
async def extract_media(
    request: Request,
    url: str = Query(..., description="Media URL"),
    api_key: str = Query(..., description="Your API Key"),
    media_type: Optional[str] = Query(
        "video",
        description="Comma separated: video,photo,audio,document,other"
    ),
    quality: Optional[int] = Query(
        None,
        description="Max resolution (e.g., 720)"
    ),
    file_size: Optional[str] = Query(
        None,
        description="Max file size (e.g., 50MB, 1GB)"
    ),
    file_ext: Optional[str] = Query(
        None,
        description="File extension filter (mp4, mp3, jpg)"
    )
):
    """
    Extract downloadable media URLs with optional filters.

    Rate limit is applied per IP.
    """

    if api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")

    media_types = [m.strip().lower() for m in media_type.split(",")]
    allowed_types = ["video", "photo", "audio", "document", "other"]

    for m in media_types:
        if m not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid media_type '{m}'. Allowed: {allowed_types}"
            )

    filesize_limit = parse_filesize_limit(file_size)

    try:
        ydl_opts = {
            "quiet": True,
            "skip_download": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        response = {
            "title": info.get("title"),
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration"),
            "files": []
        }

        formats = info.get("formats", [])

        for f in formats:

            ext = f.get("ext")
            resolution = f.get("resolution")
            filesize = f.get("filesize") or f.get("filesize_approx")

            detected_type = "other"

            if f.get("vcodec") != "none":
                detected_type = "video"
            elif f.get("acodec") != "none":
                detected_type = "audio"

            if ext in ["jpg", "png", "webp"]:
                detected_type = "photo"

            if ext in ["pdf", "doc", "docx", "ppt", "pptx"]:
                detected_type = "document"

            if detected_type not in media_types:
                continue

            if quality and detected_type in ["video", "photo"]:
                res_number = resolution_to_number(resolution)
                if res_number and res_number > quality:
                    continue

            if filesize_limit and filesize:
                if filesize > filesize_limit:
                    continue

            if file_ext and ext != file_ext.lower():
                continue

            has_audio = (
                f.get("acodec") != "none"
                and f.get("acodec") is not None
            )

            response["files"].append({
                "type": detected_type,
                "url": f.get("url"),
                "resolution": resolution,
                "has_audio": has_audio,
                "filesize_bytes": filesize,
                "filesize_human": human_readable_size(filesize),
                "extension": ext
            })

        return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

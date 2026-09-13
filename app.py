#!/usr/bin/env python3
"""
YouTube Transcript Studio
A modern, responsive web application and developer REST API for exploring, translating,
and exporting YouTube transcripts using youtube-transcript-api.
"""

import os
import re
import sys
import time
import argparse
import webbrowser
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse, parse_qs

from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import (
    TextFormatter,
    JSONFormatter,
    SRTFormatter,
    WebVTTFormatter,
)
from youtube_transcript_api.proxies import GenericProxyConfig, WebshareProxyConfig
from youtube_transcript_api._errors import (
    YouTubeTranscriptApiException,
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
    InvalidVideoId,
    IpBlocked,
    RequestBlocked,
    AgeRestricted,
    VideoUnplayable,
    NotTranslatable,
    TranslationLanguageNotAvailable,
)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
INDEX_FILE = TEMPLATES_DIR / "index.html"

app = FastAPI(
    title="YouTube Transcript API & Studio",
    description=(
        "Fast, lightweight API and Web UI to retrieve, translate, and export YouTube transcripts. "
        "Built-in full-text output and formatting options, perfectly suited for webhooks, automation, and developer workflows."
    ),
    version="1.2.4",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def extract_video_id(url_or_id: str) -> str:
    """Extract 11-character YouTube video ID from various URL formats or raw ID."""
    raw = (url_or_id or "").strip()
    if raw.startswith(r"\-"):
        raw = raw[1:]

    # Direct standard video ID check (11 alphanumeric with '-' and '_')
    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", raw):
        return raw

    parsed = urlparse(raw)

    # youtu.be/<id>
    if "youtu.be" in (parsed.netloc or ""):
        path = parsed.path.lstrip("/")
        video_id = path.split("/")[0] if path else raw
        return video_id.split("?")[0]

    # youtube.com
    if "youtube.com" in (parsed.netloc or ""):
        qs = parse_qs(parsed.query)
        if "v" in qs and qs["v"]:
            return qs["v"][0]

        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0] in ("shorts", "embed", "v", "live"):
            return parts[1]

    # Fallback regex search for an 11-char video ID in the string
    match = re.search(r"(?:v=|\/|vi\/|youtu\.be\/)([a-zA-Z0-9_-]{11})", raw)
    if match:
        return match.group(1)

    return raw


def build_proxy_config(
    proxy_http: Optional[str] = None,
    proxy_https: Optional[str] = None,
    webshare_user: Optional[str] = None,
    webshare_pass: Optional[str] = None,
) -> Optional[Any]:
    """Instantiate appropriate ProxyConfig based on user inputs."""
    if webshare_user and webshare_pass:
        return WebshareProxyConfig(
            proxy_username=webshare_user,
            proxy_password=webshare_pass,
        )
    if proxy_http or proxy_https:
        return GenericProxyConfig(
            http_url=proxy_http,
            https_url=proxy_https,
        )
    return None


def format_transcript_outputs(transcript: Any) -> Dict[str, str]:
    """Generate TXT, SRT, VTT, and formatted JSON representations."""
    return {
        "text": TextFormatter().format_transcript(transcript),
        "srt": SRTFormatter().format_transcript(transcript),
        "vtt": WebVTTFormatter().format_transcript(transcript),
        "json": JSONFormatter().format_transcript(transcript, indent=2),
    }


def humanize_error(err: Exception, video_id: str) -> Dict[str, str]:
    """Produce clean, actionable error messages."""
    if isinstance(err, TranscriptsDisabled):
        return {
            "error_title": "Subtitles Disabled",
            "error_message": f"Subtitles/transcripts have been disabled by the owner for video {video_id}.",
        }
    if isinstance(err, NoTranscriptFound):
        return {
            "error_title": "No Transcript Found",
            "error_message": f"No transcript matching the requested language was found for video {video_id}.",
        }
    if isinstance(err, VideoUnavailable):
        return {
            "error_title": "Video Unavailable",
            "error_message": f"The video {video_id} is unavailable, private, or has been removed.",
        }
    if isinstance(err, (IpBlocked, RequestBlocked)):
        return {
            "error_title": "YouTube IP Blocked / Rate-Limited",
            "error_message": (
                "YouTube has temporarily rate-limited requests from your IP address. "
                "You can bypass this by configuring a residential or custom proxy."
            ),
        }
    if isinstance(err, AgeRestricted):
        return {
            "error_title": "Age Restricted Video",
            "error_message": "This video is age restricted and cannot be accessed without authentication.",
        }
    if isinstance(err, (InvalidVideoId, ValueError)):
        return {
            "error_title": "Invalid Video Link / ID",
            "error_message": f"Could not recognize a valid YouTube video ID from '{video_id}'.",
        }
    if isinstance(err, NotTranslatable):
        return {
            "error_title": "Not Translatable",
            "error_message": "This transcript cannot be translated to other languages.",
        }
    if isinstance(err, TranslationLanguageNotAvailable):
        return {
            "error_title": "Language Unavailable",
            "error_message": "The requested translation language is not available for this transcript.",
        }

    return {
        "error_title": "Failed to Fetch Transcript",
        "error_message": str(err),
    }


def get_transcript_payload(
    url_or_id: str,
    language: Optional[str] = None,
    translate: Optional[str] = None,
    proxy_http: Optional[str] = None,
    proxy_https: Optional[str] = None,
    webshare_user: Optional[str] = None,
    webshare_pass: Optional[str] = None,
) -> Dict[str, Any]:
    """Unified core function to fetch, translate, and format transcripts."""
    video_id = extract_video_id(url_or_id)
    if not video_id or len(video_id) < 5:
        raise ValueError(f"Invalid YouTube URL or Video ID: '{url_or_id}'")

    proxy_config = build_proxy_config(
        proxy_http=proxy_http,
        proxy_https=proxy_https,
        webshare_user=webshare_user,
        webshare_pass=webshare_pass,
    )

    ytt_api = YouTubeTranscriptApi(proxy_config=proxy_config)
    transcript_list = ytt_api.list(video_id)

    # Collect available transcripts
    available_transcripts = []
    for t in transcript_list:
        available_transcripts.append(
            {
                "language": t.language,
                "language_code": t.language_code,
                "is_generated": t.is_generated,
                "is_translatable": t.is_translatable,
            }
        )

    if not available_transcripts:
        raise NoTranscriptFound(video_id)

    # Determine which transcript to fetch
    transcript_obj = None
    if language:
        try:
            transcript_obj = transcript_list.find_transcript([language])
        except Exception:
            pass

    if transcript_obj is None:
        try:
            transcript_obj = transcript_list.find_transcript(["en", "en-US", "en-GB"])
        except Exception:
            transcript_obj = next(iter(transcript_list))

    # Optional translation
    if translate:
        transcript_obj = transcript_obj.translate(translate)

    fetched = transcript_obj.fetch()

    # Collect translation languages available
    translation_languages_dict = {}
    for t in transcript_list:
        if t.is_translatable:
            for tl in t.translation_languages:
                translation_languages_dict[tl.language_code] = tl.language

    translation_languages = [
        {"language_code": code, "language": name}
        for code, name in sorted(translation_languages_dict.items(), key=lambda x: x[1])
    ]

    snippets = fetched.to_raw_data()
    full_text = " ".join(s.get("text", "") for s in snippets)
    word_count = len(full_text.split()) if full_text else 0
    duration_seconds = round(snippets[-1]["start"] + snippets[-1]["duration"], 2) if snippets else 0.0

    formatted = format_transcript_outputs(fetched)

    return {
        "video_id": video_id,
        "language": fetched.language,
        "language_code": fetched.language_code,
        "is_generated": fetched.is_generated,
        "is_translated": bool(translate),
        "word_count": word_count,
        "duration_seconds": duration_seconds,
        "text": full_text,
        "snippets": snippets,
        "available_transcripts": available_transcripts,
        "translation_languages": translation_languages,
        "formatted": formatted,
    }


# Pydantic Models
class FetchRequest(BaseModel):
    url_or_id: str = Field(..., description="YouTube URL or Video ID")
    language: Optional[str] = Field(None, description="Requested language code (e.g. 'en', 'es')")
    proxy_http: Optional[str] = Field(None, description="Custom HTTP proxy")
    proxy_https: Optional[str] = Field(None, description="Custom HTTPS proxy")
    webshare_user: Optional[str] = Field(None, description="Webshare proxy username")
    webshare_pass: Optional[str] = Field(None, description="Webshare proxy password")


class TranslateRequest(BaseModel):
    video_id: str
    source_language: str
    target_language: str
    proxy_http: Optional[str] = None
    proxy_https: Optional[str] = None
    webshare_user: Optional[str] = None
    webshare_pass: Optional[str] = None


class ApiTranscriptRequest(BaseModel):
    url: str = Field(..., description="YouTube video URL or Video ID")
    lang: Optional[str] = Field(None, description="Language code (e.g., 'en', 'es', 'de')")
    translate: Optional[str] = Field(None, description="Target language code to translate into")
    format: Optional[str] = Field("json", description="Output format: 'json', 'text', 'srt', or 'vtt'")
    proxy_http: Optional[str] = None
    proxy_https: Optional[str] = None
    webshare_user: Optional[str] = None
    webshare_pass: Optional[str] = None


# Endpoints
@app.get("/", response_class=HTMLResponse, tags=["Web UI"])
async def get_index():
    """Serve the interactive Web UI."""
    if INDEX_FILE.exists():
        content = INDEX_FILE.read_text(encoding="utf-8")
        return HTMLResponse(content=content)
    return HTMLResponse("<h1>Error: templates/index.html not found</h1>", status_code=500)


@app.get("/api/health", tags=["System"])
async def health():
    """Health check endpoint for container orchestrators and monitoring."""
    return {"status": "ok", "app": "YouTube Transcript Studio", "version": "1.2.4"}


# ==============================================================================
# REST API Endpoints
# ==============================================================================

@app.get("/api/transcript", tags=["REST API"])
async def get_transcript_api(
    url: str = Query(..., description="YouTube video URL or Video ID (e.g. 'https://www.youtube.com/watch?v=dQw4w9WgXcQ' or 'dQw4w9WgXcQ')"),
    lang: Optional[str] = Query(None, description="Language code (e.g. 'en', 'es'). Defaults to English or the first available caption track."),
    translate: Optional[str] = Query(None, description="Target language code to translate transcript into (e.g. 'es', 'fr', 'de')."),
    format: str = Query("json", description="Output format: 'json', 'text', 'srt', or 'vtt'"),
    proxy_http: Optional[str] = Query(None, description="Optional HTTP proxy URL"),
    proxy_https: Optional[str] = Query(None, description="Optional HTTPS proxy URL"),
    webshare_user: Optional[str] = Query(None, description="Optional Webshare username"),
    webshare_pass: Optional[str] = Query(None, description="Optional Webshare password"),
):
    """
    Get YouTube transcript via simple GET request.
    Returns plain text, SRT, VTT, or rich JSON containing full text and timestamped snippets.
    """
    try:
        data = get_transcript_payload(
            url_or_id=url,
            language=lang,
            translate=translate,
            proxy_http=proxy_http,
            proxy_https=proxy_https,
            webshare_user=webshare_user,
            webshare_pass=webshare_pass,
        )

        fmt = (format or "json").lower().strip()
        if fmt in ("text", "plain", "txt"):
            return PlainTextResponse(content=data["text"], media_type="text/plain; charset=utf-8")
        if fmt == "srt":
            return PlainTextResponse(content=data["formatted"]["srt"], media_type="text/plain; charset=utf-8")
        if fmt == "vtt":
            return Response(content=data["formatted"]["vtt"], media_type="text/vtt; charset=utf-8")

        # Default: JSON format
        return {
            "success": True,
            "video_id": data["video_id"],
            "language": data["language"],
            "language_code": data["language_code"],
            "is_generated": data["is_generated"],
            "is_translated": data["is_translated"],
            "word_count": data["word_count"],
            "duration_seconds": data["duration_seconds"],
            "text": data["text"],
            "snippets": data["snippets"],
            "srt": data["formatted"]["srt"],
            "vtt": data["formatted"]["vtt"],
        }

    except Exception as e:
        video_id = extract_video_id(url)
        err_info = humanize_error(e, video_id)
        return JSONResponse(status_code=400, content={"success": False, **err_info})


@app.post("/api/transcript", tags=["REST API"])
async def post_transcript_api(req: ApiTranscriptRequest):
    """
    Get YouTube transcript via POST with JSON body.
    """
    return await get_transcript_api(
        url=req.url,
        lang=req.lang,
        translate=req.translate,
        format=req.format or "json",
        proxy_http=req.proxy_http,
        proxy_https=req.proxy_https,
        webshare_user=req.webshare_user,
        webshare_pass=req.webshare_pass,
    )


@app.get("/api/languages", tags=["REST API"])
async def get_video_languages(
    url: str = Query(..., description="YouTube video URL or Video ID"),
    proxy_http: Optional[str] = Query(None),
    proxy_https: Optional[str] = Query(None),
    webshare_user: Optional[str] = Query(None),
    webshare_pass: Optional[str] = Query(None),
):
    """List all available transcript tracks and translation languages for a video."""
    video_id = extract_video_id(url)
    try:
        proxy_config = build_proxy_config(
            proxy_http=proxy_http,
            proxy_https=proxy_https,
            webshare_user=webshare_user,
            webshare_pass=webshare_pass,
        )
        ytt_api = YouTubeTranscriptApi(proxy_config=proxy_config)
        transcript_list = ytt_api.list(video_id)

        available_transcripts = [
            {
                "language": t.language,
                "language_code": t.language_code,
                "is_generated": t.is_generated,
                "is_translatable": t.is_translatable,
            }
            for t in transcript_list
        ]

        tl_dict = {}
        for t in transcript_list:
            if t.is_translatable:
                for tl in t.translation_languages:
                    tl_dict[tl.language_code] = tl.language

        translation_languages = [
            {"language_code": code, "language": name}
            for code, name in sorted(tl_dict.items(), key=lambda x: x[1])
        ]

        return {
            "success": True,
            "video_id": video_id,
            "transcripts": available_transcripts,
            "translation_languages": translation_languages,
        }
    except Exception as e:
        err_info = humanize_error(e, video_id)
        return JSONResponse(status_code=400, content={"success": False, **err_info})


# ==============================================================================
# Web UI Endpoints
# ==============================================================================

@app.post("/api/fetch", tags=["Web UI"])
async def fetch_transcript(req: FetchRequest):
    """Fetch transcripts and available languages for the Web UI."""
    try:
        data = get_transcript_payload(
            url_or_id=req.url_or_id,
            language=req.language,
            proxy_http=req.proxy_http,
            proxy_https=req.proxy_https,
            webshare_user=req.webshare_user,
            webshare_pass=req.webshare_pass,
        )

        return {
            "success": True,
            "video_id": data["video_id"],
            "transcript": {
                "language": data["language"],
                "language_code": data["language_code"],
                "is_generated": data["is_generated"],
                "snippets": data["snippets"],
            },
            "available_transcripts": data["available_transcripts"],
            "translation_languages": data["translation_languages"],
            "formatted": data["formatted"],
        }
    except Exception as e:
        video_id = extract_video_id(req.url_or_id)
        err_info = humanize_error(e, video_id)
        return JSONResponse(status_code=400, content={"success": False, **err_info})


@app.post("/api/translate", tags=["Web UI"])
async def translate_transcript(req: TranslateRequest):
    """Translate an existing transcript to another language for the Web UI."""
    try:
        data = get_transcript_payload(
            url_or_id=req.video_id,
            language=req.source_language,
            translate=req.target_language,
            proxy_http=req.proxy_http,
            proxy_https=req.proxy_https,
            webshare_user=req.webshare_user,
            webshare_pass=req.webshare_pass,
        )

        return {
            "success": True,
            "video_id": req.video_id,
            "transcript": {
                "language": data["language"],
                "language_code": data["language_code"],
                "is_generated": data["is_generated"],
                "snippets": data["snippets"],
            },
            "formatted": data["formatted"],
        }
    except Exception as e:
        err_info = humanize_error(e, req.video_id)
        return JSONResponse(status_code=400, content={"success": False, **err_info})


def open_browser(url: str, delay: float = 1.2):
    """Open default web browser after short server startup delay."""
    time.sleep(delay)
    webbrowser.open(url)


def main():
    parser = argparse.ArgumentParser(description="Run YouTube Transcript Studio Web UI & API")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind to (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8010, help="Port to listen on (default: 8010)")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open the browser")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")

    args = parser.parse_args()

    host = os.environ.get("HOST", args.host)
    port = int(os.environ.get("PORT", str(args.port)))
    no_browser = args.no_browser or os.environ.get("NO_BROWSER", "").lower() in ("1", "true", "yes")

    url = f"http://{host}:{port}"
    print("=" * 60)
    print("  YouTube Transcript Studio & API")
    print(f"  Web UI:       {url}")
    print(f"  Swagger Docs: {url}/docs")
    print("  Press Ctrl+C to stop.")
    print("=" * 60)

    if not no_browser:
        threading.Thread(target=open_browser, args=(url,), daemon=True).start()

    uvicorn.run("app:app", host=host, port=port, reload=args.reload)


if __name__ == "__main__":
    main()

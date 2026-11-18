import os
import re
import tempfile
import threading
import time
import subprocess
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, Header, HTTPException
from faster_whisper import WhisperModel

app = FastAPI(title="VEXARO CLIPS Processor", version="0.1.0")
API_TOKEN = os.environ.get("VIDEO_PROCESSOR_TOKEN", "")
MODEL_SIZE = os.environ.get("WHISPER_MODEL", "base")
MODEL_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
MODEL_COMPUTE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
MAX_SOURCE_MB = int(os.environ.get("MAX_SOURCE_MB", "50"))

_model = None
_model_lock = threading.Lock()
_jobs: dict[str, str] = {}
_jobs_lock = threading.Lock()


def whisper_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = WhisperModel(
                    MODEL_SIZE,
                    device=MODEL_DEVICE,
                    compute_type=MODEL_COMPUTE,
                )
    return _model


def callback(url: str, authorization: str, payload: dict[str, Any]):
    response = requests.post(
        url,
        json=payload,
        headers={"Authorization": authorization, "Content-Type": "application/json"},
        timeout=30,
    )
    response.raise_for_status()


def run_ffmpeg(args: list[str]):
    result = subprocess.run(args, capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "FFmpeg failed")[-1200:])


def timestamp_srt(seconds: float) -> str:
    millis = max(0, int(seconds * 1000))
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{ms:03}"


def clean_caption(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def choose_highlights(segments: list[dict[str, Any]], count: int, duration: float):
    if not segments:
        return []
    # First-pass ranking: complete speech windows with useful transcript density.
    # This is intentionally transparent; a semantic highlight model can replace it later.
    windows = []
    target = min(38.0, max(18.0, duration / max(1, count * 1.4)))
    step = max(8.0, target * 0.55)
    start = 0.0
    while start < duration and len(windows) < 300:
        end = min(duration, start + target)
        inside = [s for s in segments if s["end"] > start and s["start"] < end]
        words = sum(len(s["text"].split()) for s in inside)
        if words >= 12:
            text = " ".join(s["text"] for s in inside).lower()
            hook_terms = ("why", "how", "secret", "mistake", "best", "worst", "never", "important", "because", "amazing", "problem", "solution")
            hook_score = sum(1 for term in hook_terms if term in text)
            avg_conf = sum(s.get("confidence", 0.5) for s in inside) / len(inside)
            density = words / max(1.0, end - start)
            score = min(density, 4.0) + hook_score * 0.35 + avg_conf
            windows.append({
                "start": max(0.0, start),
                "end": end,
                "score": round(score, 3),
                "text": " ".join(s["text"] for s in inside)[:500],
            })
        start += step
    selected = []
    for candidate in sorted(windows, key=lambda item: item["score"], reverse=True):
        if all(candidate["end"] <= item["start"] or candidate["start"] >= item["end"] for item in selected):
            selected.append(candidate)
        if len(selected) >= count:
            break
    return sorted(selected, key=lambda item: item["start"])


def make_srt(segments: list[dict[str, Any]], start: float, end: float, path: Path):
    rows = []
    index = 1
    for segment in segments:
        left = max(start, segment["start"])
        right = min(end, segment["end"])
        text = clean_caption(segment["text"])
        if right <= left or not text:
            continue
        rows.extend([
            str(index),
            f"{timestamp_srt(left - start)} --> {timestamp_srt(right - start)}",
            text,
            "",
        ])
        index += 1
    path.write_text("\n".join(rows), encoding="utf-8")


def render_clip(source: Path, output: Path, srt: Path, start: float, end: float, ratio: str):
    if ratio == "9:16":
        fit = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
    elif ratio == "1:1":
        fit = "scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080"
    else:
        fit = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2"
    subtitle_path = str(srt).replace("\\", "/").replace(":", "\\:")
    video_filter = f"{fit},subtitles='{subtitle_path}':force_style='FontName=DejaVu Sans,FontSize=22,Outline=2,Shadow=1,Alignment=2,MarginV=70'"
    run_ffmpeg([
        "ffmpeg", "-y", "-ss", str(start), "-i", str(source), "-t", str(end - start),
        "-vf", video_filter, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(output),
    ])


def process_job(payload: dict[str, Any]):
    job_id = payload["job_id"]
    callback_url = payload["callback_url"]
    callback_auth = payload["callback_authorization"]
    try:
        callback(callback_url, callback_auth, {
            "job_id": job_id, "status": "processing",
            "pipeline_stage": "downloading", "progress_percent": 10,
        })
        with tempfile.TemporaryDirectory(prefix="vexaro-") as tmp:
            root = Path(tmp)
            source = root / "source-video"
            response = requests.get(payload["source_video_url"], stream=True, timeout=(20, 180))
            response.raise_for_status()
            total = 0
            with source.open("wb") as stream:
                for chunk in response.iter_content(1024 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_SOURCE_MB * 1024 * 1024:
                        raise RuntimeError(f"Source video exceeds {MAX_SOURCE_MB} MB.")
                    stream.write(chunk)

            probe = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(source)
            ], capture_output=True, text=True, timeout=30)
            if probe.returncode != 0:
                raise RuntimeError("The uploaded file is not a supported video.")
            duration = float(probe.stdout.strip())
            if duration <= 0 or duration > 3 * 60 * 60:
                raise RuntimeError("Video duration is outside the supported range.")

            callback(callback_url, callback_auth, {
                "job_id": job_id, "status": "processing",
                "pipeline_stage": "transcribing", "progress_percent": 25,
            })
            segments_iter, info = whisper_model().transcribe(
                str(source), vad_filter=True, beam_size=3
            )
            transcript_segments = []
            for segment in segments_iter:
                transcript_segments.append({
                    "start": round(float(segment.start), 3),
                    "end": round(float(segment.end), 3),
                    "text": clean_caption(segment.text),
                    "confidence": round(max(0.0, min(1.0, 1.0 + float(segment.avg_logprob))), 3),
                })
            transcript = {
                "language": getattr(info, "language", None),
                "segments": transcript_segments,
            }
            requested = max(1, min(50, int(payload.get("requested_clip_count", 5))))
            highlights = choose_highlights(transcript_segments, requested, duration)
            if not highlights:
                raise RuntimeError("No clear speech segments were found to create clips.")

            callback(callback_url, callback_auth, {
                "job_id": job_id, "status": "processing",
                "pipeline_stage": "rendering", "progress_percent": 55,
                "transcript": transcript, "highlights": highlights,
            })

            targets = payload.get("output_upload_targets", [])
            if len(targets) < len(highlights):
                raise RuntimeError("Not enough secure output upload targets were supplied.")

            completed = []
            ratio = payload.get("aspect_ratio", "9:16")
            for index, highlight in enumerate(highlights):
                clip_file = root / f"clip-{index + 1:02}.mp4"
                subtitle_file = root / f"clip-{index + 1:02}.srt"
                make_srt(transcript_segments, highlight["start"], highlight["end"], subtitle_file)
                render_clip(source, clip_file, subtitle_file, highlight["start"], highlight["end"], ratio)

                target = targets[index]
                upload_url = target.get("upload_url")
                if not upload_url:
                    raise RuntimeError("A secure output upload URL is missing.")
                with clip_file.open("rb") as clip_stream:
                    uploaded = requests.put(
                        upload_url, data=clip_stream,
                        headers={"Content-Type": "video/mp4"}, timeout=(20, 300),
                    )
                uploaded.raise_for_status()
                completed.append({
                    "storage_path": target["storage_path"],
                    "title": f"Highlight {index + 1}",
                    "start_seconds": highlight["start"],
                    "end_seconds": highlight["end"],
                })
                progress = 60 + int(35 * (index + 1) / len(highlights))
                callback(callback_url, callback_auth, {
                    "job_id": job_id, "status": "processing",
                    "pipeline_stage": "uploading", "progress_percent": progress,
                })

            callback(callback_url, callback_auth, {
                "job_id": job_id, "status": "completed",
                "transcript": transcript, "highlights": highlights, "clips": completed,
            })
        with _jobs_lock:
            _jobs[job_id] = "completed"
    except Exception as exc:
        safe_error = str(exc)[:300] or "Video processing failed."
        try:
            callback(callback_url, callback_auth, {
                "job_id": job_id, "status": "failed", "error": safe_error,
            })
        except Exception:
            pass
        with _jobs_lock:
            _jobs[job_id] = "failed"


@app.get("/health")
def health():
    return {"ok": True, "service": "vexaro-clips-processor"}


@app.post("/jobs", status_code=202)
def create_job(payload: dict[str, Any], authorization: str | None = Header(default=None)):
    if not API_TOKEN:
        raise HTTPException(status_code=503, detail="Processor token is not configured.")
    if authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized.")
    required = ("job_id", "source_video_url", "callback_url", "callback_authorization", "output_upload_targets")
    if any(key not in payload for key in required):
        raise HTTPException(status_code=400, detail="Missing required processing fields.")
    job_id = str(payload["job_id"])
    with _jobs_lock:
        if job_id in _jobs:
            return {"job_id": job_id, "status": _jobs[job_id]}
        _jobs[job_id] = "accepted"
    thread = threading.Thread(target=process_job, args=(payload,), daemon=True)
    thread.start()
    return {"job_id": job_id, "status": "accepted"}


@app.get("/health/ready")
def ready():
    return {"ok": True, "model": MODEL_SIZE, "device": MODEL_DEVICE}

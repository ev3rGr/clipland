"""Speech-to-text with word timestamps.

  local          - faster-whisper on your GPU/CPU (free, offline). Model size is configurable.
  openai_compat  - any OpenAI-compatible /audio/transcriptions endpoint (Groq whisper-large-v3 is free-tier and very
                   fast; OpenAI whisper-1 also works).
"""
import ctypes
import glob
import os
import site
import subprocess
import tempfile
import threading
from pathlib import Path

import httpx

from . import settings


def _preload_cuda_libs():
    # pip-installed CUDA libs (nvidia-cublas-cu12, nvidia-cudnn-cu12) aren't on the loader path by default
    for sp in site.getsitepackages():
        for pattern in ("nvidia/cublas/lib/libcublas*.so*", "nvidia/cudnn/lib/libcudnn*.so*"):
            for lib in sorted(glob.glob(os.path.join(sp, pattern))):
                try:
                    ctypes.CDLL(lib, mode=ctypes.RTLD_GLOBAL)
                except OSError:
                    pass


_preload_cuda_libs()

WHISPER_SIZES = ["tiny", "base", "small", "medium", "large-v3-turbo", "large-v3"]

_model = None
_model_info = {}
_lock = threading.Lock()


def get_model(size=None):
    global _model
    size = size or settings.get()["transcribe"]["whisper_model"] or "small"
    with _lock:
        if _model is not None and _model_info.get("size") == size:
            return _model
        from faster_whisper import WhisperModel
        import ctranslate2
        _model = None
        if ctranslate2.get_cuda_device_count() > 0 and os.environ.get("CUDA_VISIBLE_DEVICES") != "":
            try:
                _model = WhisperModel(size, device="cuda", compute_type="int8_float16")
                _model_info.update(size=size, device="cuda")
            except Exception as e:
                print("CUDA whisper failed, falling back to CPU:", e)
        if _model is None:
            _model = WhisperModel(size, device="cpu", compute_type="int8", cpu_threads=max(2, os.cpu_count() - 2))
            _model_info.update(size=size, device="cpu")
        return _model


def unload():
    """Drop the Whisper model so its VRAM is freed. Returns True if one was loaded."""
    global _model
    import gc
    with _lock:
        if _model is None:
            return False
        _model = None
        _model_info.clear()
    gc.collect()
    return True


def model_info():
    cfg = settings.get()["transcribe"]
    if cfg["provider"] == "openai_compat":
        return {"size": cfg["api_model"], "device": "api"}
    return dict(_model_info) if _model_info.get("size") == cfg["whisper_model"] else {"size": cfg["whisper_model"], "device": "not loaded"}


def signature():
    """Changes whenever the transcription engine changes (used for transcript cache keys)."""
    cfg = settings.get()["transcribe"]
    return f"api:{cfg['api_model']}" if cfg["provider"] == "openai_compat" else f"local:{cfg['whisper_model']}"


def transcribe(path, job=None, p0=0.0, p1=1.0, language=None, duration=None):
    """Returns {"language", "segments": [{start,end,text,words:[{start,end,word}]}]}"""
    if settings.get()["transcribe"]["provider"] == "openai_compat":
        return _transcribe_api(path, job, p0, p1, language)
    return _transcribe_local(path, job, p0, p1, language, duration)


def _transcribe_local(path, job, p0, p1, language, duration):
    if job:
        job.update(p0, "Loading speech model")
    model = get_model()
    from .media import load_audio_mono
    audio = load_audio_mono(path, 16000)
    if audio.size < 1600:
        return {"language": language or "en", "segments": []}
    try:
        segs, info = model.transcribe(
            audio, language=language or None, word_timestamps=True, vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500}, beam_size=5,
        )
        total = duration or info.duration or 1
        out = []
        for s in segs:
            words = [{"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word.strip()}
                     for w in (s.words or []) if w.word.strip()]
            out.append({"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip(), "words": words})
            if job:
                job.update(p0 + (p1 - p0) * min(1.0, s.end / total), f"Transcribing {int(100 * min(1, s.end / total))}%")
    except RuntimeError as e:
        if any(k in str(e).lower() for k in ("cuda", "cublas", "cudnn")) and _model_info.get("device") == "cuda":
            global _model
            _model = None
            os.environ["CUDA_VISIBLE_DEVICES"] = ""
            return _transcribe_local(path, job, p0, p1, language, duration)
        raise
    return {"language": info.language, "segments": out}


def _transcribe_api(path, job, p0, p1, language, chunk_s=1200):
    cfg = settings.get()["transcribe"]
    base = cfg["api_base_url"].rstrip("/")
    headers = {"Authorization": f"Bearer {cfg['api_key']}"} if cfg["api_key"] else {}
    with tempfile.TemporaryDirectory() as td:
        # small mono mp3 chunks keep each upload under the usual 25MB limit
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame",
                        "-b:a", "48k", "-f", "segment", "-segment_time", str(chunk_s), str(Path(td) / "c%03d.mp3")], check=True)
        chunks = sorted(Path(td).glob("c*.mp3"))
        segments, lang = [], language or ""
        for ci, ch in enumerate(chunks):
            if job:
                job.update(p0 + (p1 - p0) * ci / max(1, len(chunks)), f"Transcribing via API ({ci + 1}/{len(chunks)})")
            offset = ci * chunk_s
            data = [("model", cfg["api_model"]), ("response_format", "verbose_json"),
                    ("timestamp_granularities[]", "word"), ("timestamp_granularities[]", "segment")]
            if language:
                data.append(("language", language))
            with ch.open("rb") as f:
                r = httpx.post(f"{base}/audio/transcriptions", headers=headers, data=data,
                               files={"file": (ch.name, f, "audio/mpeg")}, timeout=600)
            if r.status_code >= 400:
                raise RuntimeError(f"Transcription API error {r.status_code}: {r.text[:300]}")
            d = r.json()
            lang = lang or d.get("language", "")
            words = [{"start": round(w["start"] + offset, 3), "end": round(w["end"] + offset, 3), "word": w["word"].strip()}
                     for w in d.get("words", []) if w.get("word", "").strip()]
            segs = d.get("segments") or [{"start": 0, "end": 1e9, "text": d.get("text", "")}]
            wi = 0
            for s in segs:
                st, en = s["start"] + offset, s["end"] + offset
                sw = []
                while wi < len(words) and words[wi]["start"] < en - 0.01:
                    sw.append(words[wi]); wi += 1
                if sw:
                    segments.append({"start": round(st, 3), "end": round(en, 3), "text": s.get("text", "").strip(), "words": sw})
            if wi < len(words) and segments:
                segments[-1]["words"] += words[wi:]
    _punctuate_words(segments)
    lang_map = {"english": "en", "spanish": "es", "french": "fr", "german": "de", "arabic": "ar"}
    return {"language": lang_map.get(lang.lower(), lang) if lang else "en", "segments": segments}


def _punctuate_words(segments):
    """API word lists often lack punctuation; copy it over from the segment text so sentence splitting works."""
    for s in segments:
        text = s.get("text", "")
        pos = 0
        for w in s["words"]:
            bare = w["word"].strip(".,!?;:")
            i = text.find(bare, pos) if bare else -1
            if i < 0:
                continue
            j = i + len(bare)
            while j < len(text) and text[j] in ".,!?;:'\"":
                j += 1
            w["word"] = text[i:j]
            pos = j


def all_words(transcript, start=0.0, end=1e12, offset=0.0):
    """Flatten words in [start, end), shifted by -start + offset."""
    res = []
    for s in transcript["segments"]:
        if s["end"] < start or s["start"] > end:
            continue
        for w in s["words"]:
            if w["start"] >= start - 0.05 and w["end"] <= end + 0.25:
                res.append({"start": max(0.0, w["start"] - start + offset), "end": w["end"] - start + offset, "word": w["word"]})
    return res

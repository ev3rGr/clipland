import shutil
import time
import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import jobs, llm, tts, captions, transcribe, settings, presets, sources, gpu
from .config import FILE_KINDS, FONTS, OUTPUTS, STATIC, WORK, resolve_file
from .media import probe, safe_name, thumbnail, encoder_name, run as run_cmd
from .pipelines import autoclip, stories, tools  # noqa: F401  (registers job handlers)

app = FastAPI(title="Clipland")
jobs.load_all()

MEDIA_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".gif", ".jpg", ".png"}


def _file_info(kind, p):
    d = {"ref": f"{kind}/{p.name}", "name": p.name.split("_", 1)[-1] if kind != "outputs" else p.name,
         "size": p.stat().st_size, "mtime": p.stat().st_mtime, "url": f"/media/{kind}/{p.name}"}
    thumb = WORK / "thumbs" / f"{kind}_{p.stem}.jpg"
    if kind == "outputs":
        sib = p.with_suffix(".jpg")
        if sib.exists() and sib != p:
            d["thumb"] = f"/media/outputs/{sib.name}"
    elif thumb.exists():
        d["thumb"] = f"/thumbs/{thumb.name}"
    return d


@app.get("/api/status")
def status():
    provider, model = llm.current()
    return {"llm_provider": provider, "llm_provider_label": llm.PROVIDER_LABELS.get(provider, provider),
            "llm_model": model, "whisper": transcribe.model_info(), "encoder": encoder_name(), "tools": tools.TOOLS,
            "vram": gpu.vram()}


@app.post("/api/gpu/release")
def gpu_release():
    busy = [j for j in jobs.listing() if j["status"] == "running" and j["kind"] in jobs.GPU_KINDS]
    if busy:
        raise HTTPException(409, "A job is using the GPU right now. Try again when it finishes.")
    return gpu.release("manual")


@app.get("/api/settings")
def get_settings():
    return {"settings": settings.public(), "ollama_models": llm.ollama_models(),
            "claude_cli": llm.claude_cli_path(), "whisper_sizes": transcribe.WHISPER_SIZES,
            "providers": llm.PROVIDER_LABELS}


@app.post("/api/settings")
def save_settings(patch: dict):
    return {"settings": settings.update(patch)}


@app.post("/api/settings/test")
def test_settings(body: dict):
    what = body.get("what", "llm")
    try:
        if what == "llm":
            return llm.test()
        # transcription test: 3 seconds of TTS-free synthetic check just validates connectivity/auth
        cfg = settings.get()["transcribe"]
        if cfg["provider"] == "local":
            transcribe.get_model()
            return {"ok": True, "model": transcribe.model_info()}
        import httpx
        r = httpx.get(cfg["api_base_url"].rstrip("/") + "/models",
                      headers={"Authorization": f"Bearer {cfg['api_key']}"}, timeout=20)
        if r.status_code >= 400:
            raise RuntimeError(f"API error {r.status_code}: {r.text[:200]}")
        return {"ok": True, "model": cfg["api_model"]}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/options")
def options():
    return {"voices": tts.featured(), "caption_styles": captions.style_list(),
            "positions": list(captions.POSITIONS.keys())}


@app.get("/api/presets")
def get_presets():
    return {**presets.public(), "vision": llm.supports_vision(), "ai": llm.available()}


@app.get("/api/voices")
def voices():
    return tts.list_voices()


@app.get("/api/files")
def list_files(kind: str = "uploads"):
    base = FILE_KINDS.get(kind)
    if base is None:
        raise HTTPException(400, "bad kind")
    files = [p for p in base.iterdir() if p.is_file() and p.suffix.lower() in MEDIA_EXT]
    if kind == "outputs":
        files = [p for p in files if not (p.suffix == ".jpg" and any(p.with_suffix(e).exists() for e in (".mp4", ".gif")))]
    return [_file_info(kind, p) for p in sorted(files, key=lambda p: -p.stat().st_mtime)]


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), kind: str = Form("uploads")):
    if kind not in ("uploads", "backgrounds", "music"):
        raise HTTPException(400, "bad kind")
    name = f"{uuid.uuid4().hex[:6]}_{safe_name(file.filename or 'upload.mp4')}"
    dest = FILE_KINDS[kind] / name
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f, length=4 * 1024 * 1024)
    try:
        info = probe(dest)
    except Exception:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "That file isn't a readable video or audio file")
    if info.get("has_video"):
        (WORK / "thumbs").mkdir(exist_ok=True)
        thumbnail(dest, WORK / "thumbs" / f"{kind}_{dest.stem}.jpg", t=min(2.0, info["duration"] / 3))
    return {**_file_info(kind, dest), **info}


@app.get("/api/url/detect")
def url_detect(url: str):
    return sources.detect(url)


@app.get("/api/url/info")
def url_info(url: str):
    try:
        return sources.info(url)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/probe")
def probe_file(ref: str):
    try:
        return probe(resolve_file(ref))
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.delete("/api/files")
def delete_file(ref: str):
    try:
        p = resolve_file(ref)
    except ValueError as e:
        raise HTTPException(404, str(e))
    p.unlink()
    for sib in (p.with_suffix(".jpg"), p.with_suffix(".srt")):
        if sib != p and sib.parent == OUTPUTS:
            sib.unlink(missing_ok=True)
    return {"ok": True}


class JobReq(BaseModel):
    params: dict = {}


@app.post("/api/jobs/{kind}")
def create_job(kind: str, req: JobReq):
    try:
        job = jobs.submit(kind, req.params)
    except KeyError:
        raise HTTPException(404, f"unknown job type {kind}")
    return job.public()


@app.get("/api/jobs")
def list_jobs():
    return jobs.listing()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "no such job")
    return job.public()


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    jobs.cancel(job_id)
    return {"ok": True}


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    jobs.delete(job_id)
    shutil.rmtree(WORK / job_id, ignore_errors=True)
    return {"ok": True}


class Prompt(BaseModel):
    kind: str
    prompt: str = ""


@app.post("/api/ai/write")
def ai_write(p: Prompt):
    fn = {"reddit": llm.reddit_story, "faketext": llm.fake_text, "script": llm.video_script}.get(p.kind)
    if not fn:
        raise HTTPException(400, "bad kind")
    try:
        return fn(p.prompt)
    except Exception as e:
        raise HTTPException(503, str(e))


class Preview(BaseModel):
    voice: str
    text: str = "Hey! This is how I sound. Pretty good, right?"
    speed: float = 1.0


@app.post("/api/tts/preview")
def tts_preview(p: Preview):
    d = WORK / "previews"
    d.mkdir(exist_ok=True)
    for old in d.glob("*.mp3"):
        if time.time() - old.stat().st_mtime > 3600:
            old.unlink(missing_ok=True)
    out = d / f"{uuid.uuid4().hex[:8]}.mp3"
    try:
        tts.synthesize(p.text[:300], p.voice, out, p.speed)
    except Exception as e:
        raise HTTPException(503, str(e))
    return {"url": f"/previews/{out.name}"}


def _preview_path(ext):
    d = WORK / "previews"
    d.mkdir(exist_ok=True)
    for old in d.iterdir():
        if time.time() - old.stat().st_mtime > 3600:
            old.unlink(missing_ok=True)
    return d / f"{uuid.uuid4().hex[:8]}.{ext}"


@app.get("/api/frame")
def source_frame(ref: str, t: float = 0.0, w: int = 960):
    """One frame of a source video (for drawing the facecam box)."""
    try:
        path = resolve_file(ref)
        info = probe(path)
    except ValueError as e:
        raise HTTPException(404, str(e))
    out = _preview_path("jpg")
    t = max(0.0, min(t, info["duration"] - 0.1))
    run_cmd(["ffmpeg", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1", "-vf", f"scale={max(160, min(w, 1920))}:-2",
             "-q:v", "3", out])
    return FileResponse(out, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.post("/api/facecam/detect")
def facecam_detect(body: dict):
    try:
        path = resolve_file(body.get("file", ""))
        info = probe(path)
    except ValueError as e:
        raise HTTPException(404, str(e))
    fc = autoclip.find_facecam(path, info, "auto")
    norm = None
    if fc:
        x, y, w, h = fc["rect"]
        norm = [x / info["width"], y / info["height"], w / info["width"], h / info["height"]]
    return {"facecam": fc, "rect": norm, "width": info["width"], "height": info["height"]}


@app.post("/api/layout/preview")
def layout_preview(body: dict):
    out = _preview_path("jpg")
    try:
        fc = autoclip.layout_preview(out=out, **body)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"url": f"/previews/{out.name}", "facecam": fc}


@app.get("/previews/{name}")
def preview_file(name: str):
    p = WORK / "previews" / safe_name(name)
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p)


@app.get("/thumbs/{name}")
def thumb_file(name: str):
    p = WORK / "thumbs" / safe_name(name)
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p)


for kind, base in FILE_KINDS.items():
    app.mount(f"/media/{kind}", StaticFiles(directory=base), name=f"media-{kind}")
app.mount("/fonts", StaticFiles(directory=FONTS), name="fonts")
app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")

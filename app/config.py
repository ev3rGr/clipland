from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("CLIPLAND_DATA", ROOT / "data"))
UPLOADS = DATA / "uploads"
BACKGROUNDS = DATA / "backgrounds"
MUSIC = DATA / "music"
OUTPUTS = DATA / "outputs"
JOBS = DATA / "jobs"
WORK = DATA / "work"
FONTS = ROOT / "assets" / "fonts"
STATIC = ROOT / "static"

for d in (UPLOADS, BACKGROUNDS, MUSIC, OUTPUTS, JOBS, WORK):
    d.mkdir(parents=True, exist_ok=True)

# Folders the UI may reference as "<kind>/<filename>"
FILE_KINDS = {"uploads": UPLOADS, "backgrounds": BACKGROUNDS, "music": MUSIC, "outputs": OUTPUTS}

WHISPER_MODEL = os.environ.get("CLIPLAND_WHISPER", "small")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("CLIPLAND_LLM", "")  # empty = first installed model

W, H = 1080, 1920  # vertical output size


def resolve_file(ref: str) -> Path:
    """Turn 'uploads/foo.mp4' into a safe absolute path."""
    if not ref or "/" not in ref:
        raise ValueError(f"bad file reference: {ref!r}")
    kind, name = ref.split("/", 1)
    base = FILE_KINDS.get(kind)
    if base is None:
        raise ValueError(f"unknown file kind: {kind}")
    p = (base / name).resolve()
    if p.parent != base.resolve() or not p.is_file():
        raise ValueError(f"file not found: {ref}")
    return p

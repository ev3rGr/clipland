import json
import random
from pathlib import Path

from ..config import BACKGROUNDS, MUSIC, OUTPUTS, WORK, W, H, resolve_file
from ..media import probe, thumbnail


def out_path(job, suffix, ext="mp4"):
    return OUTPUTS / f"{job.id}_{suffix}.{ext}"


def work_dir(job) -> Path:
    d = WORK / job.id
    d.mkdir(parents=True, exist_ok=True)
    return d


def output_entry(path: Path, title="", **extra):
    info = {}
    try:
        info = probe(path)
    except Exception:
        pass
    thumb = path.with_suffix(".jpg")
    has_thumb = info.get("has_video") and thumbnail(path, thumb, t=min(1.0, info.get("duration", 0) / 3))
    return {"file": f"outputs/{path.name}", "title": title, "duration": round(info.get("duration", 0), 2),
            "thumb": f"outputs/{thumb.name}" if has_thumb else None, **extra}


GRADIENTS = [((138, 43, 226), (255, 79, 154), (30, 144, 255)), ((0, 201, 167), (45, 107, 255), (142, 68, 173)),
             ((255, 138, 0), (229, 46, 113), (106, 0, 244))]


def _gradient_image(out_w, out_h):
    """Oversized static 3-colour gradient (cached). Animated later with a slow pan + hue drift."""
    import numpy as np
    from PIL import Image
    i = random.randrange(len(GRADIENTS))
    path = WORK / f"gradient_{i}_{out_w}x{out_h}.png"
    if not path.exists():
        w, h = int(out_w * 1.25) // 2 * 2, int(out_h * 1.25) // 2 * 2
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        t = (xx / w * 0.45 + yy / h * 0.55)[..., None]
        c0, c1, c2 = (np.array(c, np.float32) for c in GRADIENTS[i])
        img = np.where(t < 0.5, c0 + (c1 - c0) * (t / 0.5), c1 + (c2 - c1) * ((t - 0.5) / 0.5))
        Image.fromarray(img.clip(0, 255).astype(np.uint8)).save(path)
    return path


def background_input(ref, duration, out_w=W, out_h=H):
    """ffmpeg input args + filter (on that input) for a looping gameplay/b-roll background.

    ref: 'backgrounds/x.mp4', 'random', or 'gradient' (built-in animated gradient, no file needed).
    """
    path = None
    if ref == "random":
        vids = [p for p in BACKGROUNDS.iterdir() if p.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm")]
        path = random.choice(vids) if vids else None
    elif ref and ref != "gradient":
        path = resolve_file(ref)
    if path is None:
        grad = _gradient_image(out_w, out_h)
        mx = int(out_w * 1.25) // 2 * 2 - out_w
        my = int(out_h * 1.25) // 2 * 2 - out_h
        args = ["-loop", "1", "-framerate", "30", "-t", f"{duration + 1:.2f}", "-i", str(grad)]
        return args, (f"crop={out_w}:{out_h}:x='{mx / 2}+{mx / 2}*sin(t/4)':y='{my / 2}+{my / 2}*cos(t/6)',"
                      f"hue=h='t*14',setsar=1,fps=30")
    info = probe(path)
    bg_dur = info["duration"]
    args = []
    if bg_dur > duration + 2:
        args += ["-ss", f"{random.uniform(0, bg_dur - duration - 1):.2f}"]
    else:
        args += ["-stream_loop", "-1"]
    args += ["-i", str(path)]
    return args, f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},setsar=1,fps=30"


def music_input(ref):
    if not ref or ref == "none":
        return None
    if ref == "random":
        tracks = [p for p in MUSIC.iterdir() if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg", ".flac")]
        return random.choice(tracks) if tracks else None
    return resolve_file(ref)


def write_srt(words, path, max_words=7):
    from ..captions import chunk_words, _ts

    def ts(t):
        h, m, rest = _ts(t).split(":")  # h:mm:ss.cc
        sec, cs = rest.split(".")
        return f"{int(h):02d}:{m}:{sec},{cs}0"
    lines = []
    for i, ch in enumerate(chunk_words(words, max_words, 42), 1):
        lines += [str(i), f"{ts(ch[0]['start'])} --> {ts(ch[-1]['end'])}", " ".join(w["word"] for w in ch), ""]
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def save_json(path, data):
    Path(path).write_text(json.dumps(data))


def load_json(path):
    return json.loads(Path(path).read_text())

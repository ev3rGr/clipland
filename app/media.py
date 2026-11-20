"""ffmpeg / ffprobe helpers."""
import json
import re
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np

from .config import FONTS


class FFmpegError(RuntimeError):
    pass


def run(cmd, job=None, duration=None, p0=0.0, p1=1.0, label="Rendering"):
    """Run ffmpeg, optionally reporting progress (parsed from -progress) to a job."""
    cmd = [str(c) for c in cmd]
    if cmd[0] == "ffmpeg":
        cmd = ["ffmpeg", "-hide_banner", "-y", "-loglevel", "error", "-progress", "pipe:1", "-nostats"] + cmd[1:]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if job is not None and duration:
        for line in proc.stdout:
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    t = int(line.split("=")[1]) / 1e6
                except ValueError:
                    continue
                job.update(p0 + (p1 - p0) * min(1.0, t / duration), f"{label} {min(100, int(100 * t / duration))}%")
    out, err = proc.communicate()
    if proc.returncode != 0:
        raise FFmpegError(err.strip()[-1500:] or f"ffmpeg exited {proc.returncode}")
    return out


def probe(path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise FFmpegError(f"ffprobe failed: {out.stderr.strip()}")
    info = json.loads(out.stdout)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    dur = float(info["format"].get("duration") or (v or a or {}).get("duration") or 0)
    res = {"duration": dur, "has_audio": a is not None, "has_video": v is not None}
    if v:
        w, h = int(v["width"]), int(v["height"])
        rot = 0
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = abs(int(sd["rotation"]))
        if rot in (90, 270):
            w, h = h, w
        num, den = (v.get("avg_frame_rate") or "30/1").split("/")
        fps = float(num) / float(den) if float(den) else 30.0
        res.update(width=w, height=h, fps=round(fps, 3) or 30.0)
    return res


@lru_cache(maxsize=1)
def _nvenc_ok() -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.2",
             "-c:v", "h264_nvenc", "-f", "null", "-"],
            check=True, capture_output=True, timeout=30,
        )
        return True
    except Exception:
        return False


def encoder_name():
    return "h264_nvenc (GPU)" if _nvenc_ok() else "libx264 (CPU)"


def venc(quality="high"):
    """Video encoder args. NVENC when available, else x264."""
    if _nvenc_ok():
        cq = {"high": 21, "medium": 25, "low": 30}[quality]
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", cq, "-b:v", "0", "-pix_fmt", "yuv420p"]
    crf = {"high": 20, "medium": 24, "low": 29}[quality]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", crf, "-pix_fmt", "yuv420p"]


AENC = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
MP4_FLAGS = ["-movflags", "+faststart"]


def filter_path(p) -> str:
    """Escape a path for use inside an ffmpeg filtergraph option."""
    s = str(Path(p).resolve())
    return s.replace("\\", "/").replace(":", r"\:").replace("'", r"\'").replace(",", r"\,")


def ass_filter(ass_path) -> str:
    return f"ass='{filter_path(ass_path)}':fontsdir='{filter_path(FONTS)}'"


def audio_duration(path) -> float:
    return probe(path)["duration"]


def load_audio_mono(path, sr=16000, start=None, end=None) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
    if end is not None:
        cmd += ["-to", f"{end:.3f}"]
    cmd += ["-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    out = subprocess.run(cmd, capture_output=True)
    if out.returncode != 0:
        return np.zeros(0, dtype=np.float32)
    return np.frombuffer(out.stdout, dtype=np.float32)


def safe_name(name: str, default="file") -> str:
    name = Path(name).name
    name = re.sub(r"[^A-Za-z0-9._ -]+", "", name).strip().replace(" ", "_")
    return name[:120] or default


def thumbnail(src, dst, t=1.0, width=360):
    try:
        run(["ffmpeg", "-ss", f"{t:.2f}", "-i", src, "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", dst])
        return True
    except FFmpegError:
        return False

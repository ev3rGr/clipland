"""GPU housekeeping: free VRAM when the heavy work is done.

What holds GPU memory between runs:
  - the faster-whisper model (kept in this process after a transcription)
  - Ollama models (Ollama keeps them loaded ~5 min by default)
ffmpeg NVENC/NVDEC sessions free themselves when each ffmpeg process exits.
"""
import gc
import subprocess
import threading

import httpx

_lock = threading.Lock()


def vram():
    """{'used': MiB, 'total': MiB} or None without an NVIDIA GPU."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=3).stdout.strip().splitlines()[0]
        used, total = (int(x) for x in out.split(","))
        return {"used": used, "total": total}
    except Exception:
        return None


def unload_whisper():
    from . import transcribe
    return transcribe.unload()


def unload_ollama():
    """Ask Ollama to drop every loaded model from VRAM now (keep_alive=0)."""
    from .llm import OLLAMA_URL
    freed = []
    try:
        for m in httpx.get(f"{OLLAMA_URL}/api/ps", timeout=2).json().get("models", []):
            httpx.post(f"{OLLAMA_URL}/api/generate", json={"model": m["name"], "keep_alive": 0}, timeout=10)
            freed.append(m["name"])
    except Exception:
        pass
    return freed


def release(reason=""):
    with _lock:
        before = vram()
        w = unload_whisper()
        o = unload_ollama()
        gc.collect()
        after = vram()
        if o and before and after:  # Ollama frees asynchronously: wait (up to ~3s) for the drop to show
            import time
            for _ in range(15):
                if after["used"] < before["used"] - 200:
                    break
                time.sleep(0.2)
                after = vram()
    if w or o:
        print(f"[gpu] released{' after ' + reason if reason else ''}: whisper={w} ollama={o} "
              f"vram {before and before['used']} -> {after and after['used']} MiB")
    return {"whisper": w, "ollama": o, "before": before, "after": after}

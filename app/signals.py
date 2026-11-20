"""Find highlights in videos where the transcript isn't enough (gameplay, trailers, streams).

Signals, sampled every 0.5s:
  action    - loudness relative to the surrounding minute + audio onsets (gunfire, impacts, explosions, crashes)
  motion    - how much the picture changes (chases, fights, fast camera)
  cuts      - scene changes (trailers, edits)
  flash     - sudden brightness jumps (explosions, muzzle flashes)
  reactions - streamer hype words / laughter / shouting from the transcript (if transcribed)
"""
import hashlib
import re
import subprocess

import numpy as np

from .config import WORK
from .media import load_audio_mono

HOP = 0.5  # seconds per bin
VID_FPS = 4


def _key(path):
    st = path.stat()
    return hashlib.sha1(f"{path.name}:{st.st_size}:{st.st_mtime_ns}:v2".encode()).hexdigest()[:16]


def _video_signals(path, duration, job=None, p0=0.0, p1=1.0):
    w, h = 96, 54
    n = w * h
    base = ["ffmpeg", "-v", "error"]
    tail = ["-i", str(path), "-an", "-sn", "-vf", f"fps={VID_FPS},scale={w}:{h}:flags=fast_bilinear,format=gray",
            "-f", "rawvideo", "-"]
    frames_expected = max(1, int(duration * VID_FPS))
    for extra in (["-skip_frame", "nonref"], []):  # skipping non-reference frames ~halves decode time
        proc = subprocess.Popen(base + extra + tail, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        motion, bright = [], []
        prev = None
        i = 0
        while True:
            buf = proc.stdout.read(n)
            if len(buf) < n:
                break
            f = np.frombuffer(buf, np.uint8).astype(np.float32)
            bright.append(float(f.mean()))
            motion.append(float(np.mean(np.abs(f - prev))) if prev is not None else 0.0)
            prev = f
            i += 1
            if job and i % 400 == 0:
                job.update(p0 + (p1 - p0) * min(1.0, i / frames_expected), f"Scanning video {int(100 * min(1, i / frames_expected))}%")
        proc.wait()
        if i >= frames_expected * 0.6:
            break
    motion, bright = np.array(motion), np.array(bright)
    # scene cuts: a frame change far larger than the frames around it
    cuts = []
    for k in range(1, len(motion)):
        lo, hi = max(0, k - 3), min(len(motion), k + 4)
        neigh = np.concatenate([motion[lo:k], motion[k + 1:hi]])
        ref = np.median(neigh) if neigh.size else 0
        if motion[k] > 28 and motion[k] > 2.8 * ref + 6:
            cuts.append(k / VID_FPS)
    return motion, bright, cuts


def _audio_signals(path):
    sr = 16000
    audio = load_audio_mono(path, sr)
    hop = int(sr * 0.1)
    nfr = audio.size // hop
    if nfr < 2:
        return np.zeros(0), np.zeros(0)
    frames = audio[: nfr * hop].reshape(nfr, hop)
    rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-10)
    loud_db = 20 * np.log10(rms + 1e-6)
    flux = np.zeros(nfr, np.float32)
    prev = None
    win = np.hanning(hop).astype(np.float32)
    for s in range(0, nfr, 4000):  # chunked FFT keeps memory flat on long videos
        mag = np.log1p(np.abs(np.fft.rfft(frames[s:s + 4000] * win, axis=1)) * 10).astype(np.float32)
        d = np.diff(np.vstack([mag[:1] if prev is None else prev[None], mag]), axis=0)
        flux[s:s + len(mag)] = np.maximum(d, 0).sum(axis=1)
        prev = mag[-1]
    return loud_db, flux


def _to_bins(x, rate, nbins, agg=np.mean):
    out = np.zeros(nbins, np.float32)
    per = rate * HOP
    for b in range(nbins):
        seg = x[int(b * per): int((b + 1) * per)]
        out[b] = agg(seg) if len(seg) else 0.0
    return out


def _robust_z(x):
    if x.size == 0:
        return x
    med = np.median(x)
    mad = np.median(np.abs(x - med)) * 1.4826 + 1e-6
    return np.clip((x - med) / mad, -3, 6)


def _rolling(x, win, fn=np.median):
    if x.size == 0:
        return x
    half = win // 2
    pad = np.pad(x, half, mode="edge")
    # stride trick for speed on long videos
    view = np.lib.stride_tricks.sliding_window_view(pad, win)[: x.size]
    return fn(view, axis=1)


def _smooth(x, win):
    if win <= 1 or x.size == 0:
        return x
    k = np.ones(win) / win
    return np.convolve(np.pad(x, win // 2, mode="edge"), k, mode="same")[win // 2: win // 2 + x.size]


def analyze(path, duration, job=None, p0=0.0, p1=1.0):
    """Per-bin raw signals (cached per file)."""
    cache = WORK / f"signals_{_key(path)}.npz"
    if cache.exists():
        d = np.load(cache)
        return {k: d[k] for k in d.files}
    nb = max(1, int(np.ceil(duration / HOP)))
    if job:
        job.update(p0, "Listening to game audio")
    loud_db, flux = _audio_signals(path)
    motion, bright, cuts = _video_signals(path, duration, job, p0 + (p1 - p0) * 0.15, p1)
    loud = _to_bins(loud_db, 10, nb, np.max) if loud_db.size else np.zeros(nb)
    onset = _to_bins(flux, 10, nb, np.max) if flux.size else np.zeros(nb)
    mot = _to_bins(motion, VID_FPS, nb) if motion.size else np.zeros(nb)
    flash = _to_bins(np.maximum(np.diff(bright, prepend=bright[:1]), 0), VID_FPS, nb, np.max) if bright.size else np.zeros(nb)
    cut_bins = np.zeros(nb, np.float32)
    for c in cuts:
        b = int(c / HOP)
        if b < nb:
            cut_bins[b] += 1
    res = {"loud": loud, "onset": onset, "motion": mot, "flash": flash, "cuts": cut_bins, "cut_times": np.array(cuts)}
    np.savez(cache, **res)
    return res


REACTION_WORDS = {
    "oh": 1, "no": 1, "what": 1, "bro": 1.5, "yo": 1.5, "wow": 2, "dude": 1.5, "holy": 2.5, "god": 1.5, "damn": 2,
    "shit": 2, "fuck": 2.5, "fucking": 2.5, "crazy": 2, "insane": 2.5, "run": 1.5, "go": 1, "yes": 1.5, "dead": 1.5,
    "bruh": 2, "omg": 2.5, "nah": 1.5, "wait": 1, "help": 1.5, "lmao": 2, "haha": 2, "hahaha": 3, "clip": 2,
    "noo": 2, "nooo": 3, "yooo": 3, "lets": 1.5, "let's": 1.5, "sheesh": 2.5, "unreal": 2, "wtf": 3, "dude!": 2,
}


def reactions(transcript, nbins):
    out = np.zeros(nbins, np.float32)
    if not transcript:
        return out
    for seg in transcript["segments"]:
        for w in seg["words"]:
            b = int(w["start"] / HOP)
            if b >= nbins:
                continue
            word = re.sub(r"[^a-z']", "", w["word"].lower())
            score = REACTION_WORDS.get(word, 0.15)
            if w["word"].endswith("!"):
                score += 1.0
            if w["word"].isupper() and len(w["word"]) > 2:
                score += 0.8
            out[b] += score
    return out


COMPONENT_NAMES = {"action": "loud action", "onset": "impacts / gunfire", "motion": "fast action",
                   "cuts": "rapid cuts", "flash": "explosions / flashes", "reactions": "big reaction"}


def highlights(sig, duration, weights, min_len=12, max_len=40, count=6, transcript=None, snap_cuts=False):
    nb = len(sig["loud"])
    if nb < 4:
        return []
    # loudness relative to the surrounding minute matters more than absolute volume
    loud_rel = sig["loud"] - _rolling(sig["loud"], int(60 / HOP))
    comps = {
        "action": _robust_z(loud_rel) * 0.6 + _robust_z(sig["onset"]) * 0.4,
        "onset": _robust_z(sig["onset"]),
        "motion": _robust_z(_smooth(sig["motion"], 3)),
        "cuts": _smooth(sig["cuts"], 4) * 4,
        "flash": np.clip(_robust_z(sig["flash"]), 0, 6) * 0.5,
        "reactions": _robust_z(_smooth(reactions(transcript, nb), 4)) if transcript else np.zeros(nb),
    }
    wa, wm, wr, wc = (float(weights.get(k, 0)) for k in ("action", "motion", "reactions", "cuts"))
    hype = wa * comps["action"] + wm * comps["motion"] + wr * comps["reactions"] + wc * comps["cuts"] + 0.3 * wa * comps["flash"]
    hype = 0.6 * _smooth(hype, int(2 / HOP)) + 0.4 * _smooth(hype, int(6 / HOP))
    base = float(np.median(hype))
    cut_times = list(sig.get("cut_times", []))
    loud = sig["loud"]

    min_b, max_b = int(min_len / HOP), int(max_len / HOP)
    taken = np.zeros(nb, bool)
    picks = []
    order = np.argsort(-hype)
    for pk in order:
        if len(picks) >= count * 2:
            break
        if taken[max(0, pk - min_b // 2): pk + min_b // 2].any() or hype[pk] <= base:
            continue
        # grow the event while it stays hot
        thr = base + 0.35 * (hype[pk] - base)
        a = pk
        while a > 0 and hype[a - 1] > thr and pk - a < max_b:
            a -= 1
        b = pk
        while b < nb - 1 and hype[b + 1] > thr and b - pk < max_b:
            b += 1
        a -= int(3 / HOP)  # lead-in so viewers get context
        b += int(2 / HOP)
        ln = b - a
        if ln < min_b:
            extra = min_b - ln
            a -= int(extra * 0.6)
            b += extra - int(extra * 0.6)
        if b - a > max_b:
            a = pk - int(max_b * 0.62)
            b = a + max_b
        a, b = max(0, a), min(nb, b)
        start, end = a * HOP, b * HOP
        # snap boundaries: a scene cut nearby, otherwise the quietest moment nearby
        start = _snap(start, cut_times, loud, -2.5, 1.0, prefer_cut=snap_cuts)
        end = _snap(end, cut_times, loud, -1.0, 2.5, prefer_cut=snap_cuts)
        end = min(end, duration)
        if end - start < min_len * 0.7:
            continue
        sa, sb = int(start / HOP), int(end / HOP)
        if taken[sa:sb].any():
            continue
        taken[sa:sb] = True
        peak_comp = sorted(((k, comps[k][pk] * (wr if k == "reactions" else wc if k == "cuts" else wm if k == "motion" else wa))
                            for k in comps), key=lambda kv: -kv[1])
        reason = " + ".join(COMPONENT_NAMES[k] for k, v in peak_comp[:2] if v > 0.5) or "steady action"
        window = hype[sa:sb]
        raw = float(hype[pk] - base) * 0.7 + float(np.percentile(window, 75) - base) * 0.3
        picks.append({"start": round(start, 2), "end": round(end, 2), "peak": round(pk * HOP, 2), "raw": raw, "reason": reason,
                      "signals": {k: round(float(comps[k][pk]), 2) for k in ("action", "motion", "cuts", "flash", "reactions")}})
    picks.sort(key=lambda p: -p["raw"])
    if picks:  # drop filler that is far weaker than the real highlights
        top = picks[0]["raw"]
        picks = [p for i, p in enumerate(picks) if i == 0 or p["raw"] >= top * 0.25]
    picks = picks[: count * 2]
    if picks:
        hi, lo = picks[0]["raw"], picks[-1]["raw"]
        for p in picks:
            p["score"] = int(60 + 39 * (p["raw"] - lo) / (hi - lo + 1e-9))
    return picks


def _snap(t, cut_times, loud, before, after, prefer_cut=False):
    near = [c for c in cut_times if t + before <= c <= t + after]
    if near and (prefer_cut or len(near) == 1):
        return float(min(near, key=lambda c: abs(c - t)))
    a, b = max(0, int((t + before) / HOP)), min(len(loud), int((t + after) / HOP) + 1)
    if b - a < 2:
        return max(0.0, t)
    return max(0.0, (a + int(np.argmin(loud[a:b]))) * HOP)

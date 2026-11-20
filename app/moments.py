"""Find the most clip-worthy moments in a transcript.

Two engines:
  * heuristic (always available): hook phrases, speech density, loudness peaks, clean sentence boundaries
  * local LLM via Ollama (if a model is installed): reads the transcript and proposes clips + titles
"""
import re

import numpy as np

from . import llm
from .media import load_audio_mono

HOOK_WORDS = {
    "never", "always", "secret", "nobody", "everyone", "crazy", "insane", "worst", "best", "biggest", "mistake",
    "truth", "actually", "why", "how", "what", "stop", "imagine", "listen", "honestly", "literally", "money",
    "million", "billion", "dead", "died", "love", "hate", "scared", "shocked", "wrong", "problem", "real",
    "important", "must", "need", "rule", "lesson", "story", "happened", "first", "last", "only", "hack", "trick",
}
FILLER_START = {"and", "so", "but", "um", "uh", "like", "yeah", "because", "or", "then"}


def sentences(transcript):
    sents, cur = [], []
    for seg in transcript["segments"]:
        for w in seg["words"]:
            cur.append(w)
            if w["word"][-1:] in ".!?" and len(cur) >= 3:
                sents.append(cur); cur = []
        if cur and len(cur) > 25:
            sents.append(cur); cur = []
    if cur:
        sents.append(cur)
    return [{"start": s[0]["start"], "end": s[-1]["end"], "text": " ".join(w["word"] for w in s), "n": len(s)} for s in sents]


def _loudness_curve(path, duration):
    audio = load_audio_mono(path, sr=8000)
    if audio.size == 0:
        return None
    hop = 8000  # 1-second bins
    n = audio.size // hop
    rms = np.sqrt(np.mean(audio[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-9)
    return rms / (np.median(rms) + 1e-9)


def _hook_score(text):
    words = re.findall(r"[a-z']+", text.lower())
    if not words:
        return 0.0
    s = sum(1 for w in words[:20] if w in HOOK_WORDS) * 0.6
    s += 1.0 if "?" in text[:200] else 0
    s += 0.7 if re.search(r"\d", text[:120]) else 0
    s += 0.5 if words[0] in {"you", "i", "this", "the", "if", "when", "nobody", "everyone", "here's", "imagine"} else 0
    s -= 1.0 if words[0] in FILLER_START else 0
    return s


def heuristic(transcript, media_path, duration, min_len=20, max_len=60, count=5):
    sents = sentences(transcript)
    if not sents:
        return []
    loud = _loudness_curve(media_path, duration)
    target = (min_len + max_len) / 2
    cands = []
    for i in range(len(sents)):
        st = sents[i]["start"]
        n_words = 0
        for j in range(i, len(sents)):
            n_words += sents[j]["n"]
            en = sents[j]["end"]
            ln = en - st
            if ln > max_len:
                break
            if ln < min_len:
                continue
            text = " ".join(s["text"] for s in sents[i:j + 1])
            density = n_words / ln  # words per second, ~2.5 is normal
            score = _hook_score(sents[i]["text"]) * 1.6
            score += min(density, 4.0) * 0.8
            if loud is not None:
                a, b = int(st), max(int(st) + 1, int(en))
                seg = loud[a:b]
                if seg.size:
                    score += float(np.clip(seg.mean() - 1, -0.5, 1.0)) * 1.5 + float(np.clip(seg.std(), 0, 1)) * 0.8
            score += 0.6 if sents[j]["text"][-1:] in "!?" else 0
            score -= abs(ln - target) / target * 0.8
            score += sum(1 for w in re.findall(r"[a-z']+", text.lower()) if w in HOOK_WORDS) / max(1, n_words) * 6
            cands.append({"start": st, "end": en, "score": score, "text": text, "first": sents[i]["text"]})
    cands.sort(key=lambda c: -c["score"])
    picked = []
    for c in cands:
        if all(c["end"] <= p["start"] or c["start"] >= p["end"] for p in picked):
            picked.append(c)
        if len(picked) >= count:
            break
    if picked:
        hi, lo = picked[0]["score"], min(p["score"] for p in picked)
        for p in picked:
            p["score"] = int(70 + 29 * ((p["score"] - lo) / (hi - lo + 1e-9)))
            p["title"] = _auto_title(p["first"])
            p["reason"] = "Strong hook, dense speech and energy"
            p["source"] = "heuristic"
    return picked


def _auto_title(text):
    words = text.split()
    t = " ".join(words[:9]).rstrip(",.;:")
    return t + ("…" if len(words) > 9 else "")


def with_llm(transcript, duration, min_len=20, max_len=60, count=5, job=None):
    sents = sentences(transcript)
    if not sents:
        return []
    # cloud models read the whole transcript in one go; small local models get ~12 minute windows
    window_s = 4 * 3600 if llm.big_context() else 720
    windows, cur = [], []
    for idx, s in enumerate(sents):
        cur.append(idx)
        if s["end"] - sents[cur[0]]["start"] > window_s:
            windows.append(cur); cur = []
    if cur:
        windows.append(cur)
    per_window = count if len(windows) == 1 else max(2, int(np.ceil(count * 1.5 / len(windows))))
    provider, model = llm.current()
    cands = []
    for wi, win in enumerate(windows):
        if job:
            job.update(0.62 + 0.25 * wi / len(windows),
                       f"{llm.PROVIDER_LABELS.get(provider, provider)} is reading the transcript ({wi + 1}/{len(windows)})")
        listing = "\n".join(f"[{i}] ({sents[i]['start']:.1f}-{sents[i]['end']:.1f}) {sents[i]['text']}" for i in win)
        try:
            clips = llm.pick_clips(listing, per_window, min_len, max_len)
        except Exception as e:
            print("LLM moment pass failed:", e)
            if job:
                job.update(None, f"AI unavailable ({str(e)[:80]}), using heuristic")
            continue
        for c in clips:
            try:
                a, b = int(c["start_index"]), int(c["end_index"])
            except (KeyError, ValueError, TypeError):
                continue
            lo_i, hi_i = win[0], win[-1]
            a, b = max(lo_i, min(a, hi_i)), max(lo_i, min(b, hi_i))
            if a > b:
                a, b = b, a
            # stretch/trim to respect length limits along sentence boundaries
            while b + 1 < len(sents) and sents[b]["end"] - sents[a]["start"] < min_len:
                b += 1
            while b > a and sents[b]["end"] - sents[a]["start"] > max_len:
                b -= 1
            ln = sents[b]["end"] - sents[a]["start"]
            if ln < min_len * 0.6 or ln > max_len * 1.1:
                continue
            tags = [t if t.startswith("#") else "#" + t for t in (c.get("hashtags") or []) if str(t).strip()]
            cands.append({"start": sents[a]["start"], "end": sents[b]["end"], "score": int(c.get("score", 75) or 75),
                          "title": str(c.get("title", ""))[:80] or _auto_title(sents[a]["text"]),
                          "reason": str(c.get("reason", ""))[:240], "description": str(c.get("description", ""))[:400],
                          "hashtags": [str(t).replace(" ", "") for t in tags][:8], "source": model,
                          "text": " ".join(s["text"] for s in sents[a:b + 1])})
    cands.sort(key=lambda c: -c["score"])
    picked = []
    for c in cands:
        if all(c["end"] <= p["start"] or c["start"] >= p["end"] for p in picked):
            picked.append(c)
        if len(picked) >= count:
            break
    return picked


def find_moments(transcript, media_path, duration, min_len=20, max_len=60, count=5, use_ai=True, job=None):
    max_len = min(max_len, duration)
    min_len = min(min_len, max_len * 0.8)
    picked = []
    if use_ai and llm.available():
        picked = with_llm(transcript, duration, min_len, max_len, count, job)
    if len(picked) < count:
        extra = heuristic(transcript, media_path, duration, min_len, max_len, count * 2)
        for c in extra:
            if len(picked) >= count:
                break
            if all(c["end"] <= p["start"] or c["start"] >= p["end"] for p in picked):
                picked.append(c)
    for i, p in enumerate(picked):
        p["id"] = i + 1
        p["start"], p["end"] = round(p["start"], 2), round(p["end"], 2)
        p.pop("first", None)
    return picked

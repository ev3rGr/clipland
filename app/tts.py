"""Free text-to-speech via Microsoft Edge's online neural voices (edge-tts, no key needed).

Returns word-level timestamps, so captions line up without running Whisper.
"""
import asyncio
import re
import threading

import edge_tts

_voices_cache = None
_lock = threading.Lock()

FEATURED = [
    ("en-US-AndrewMultilingualNeural", "Andrew — warm male (US)"),
    ("en-US-BrianMultilingualNeural", "Brian — casual male (US)"),
    ("en-US-ChristopherNeural", "Christopher — deep male (US)"),
    ("en-US-GuyNeural", "Guy — narrator male (US)"),
    ("en-US-EricNeural", "Eric — calm male (US)"),
    ("en-US-AvaMultilingualNeural", "Ava — bright female (US)"),
    ("en-US-EmmaMultilingualNeural", "Emma — friendly female (US)"),
    ("en-US-JennyNeural", "Jenny — clear female (US)"),
    ("en-US-AriaNeural", "Aria — expressive female (US)"),
    ("en-US-AnaNeural", "Ana — child (US)"),
    ("en-GB-RyanNeural", "Ryan — male (UK)"),
    ("en-GB-SoniaNeural", "Sonia — female (UK)"),
    ("en-AU-WilliamNeural", "William — male (AU)"),
]


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def list_voices():
    global _voices_cache
    with _lock:
        if _voices_cache is None:
            try:
                vs = _run(edge_tts.list_voices())
                _voices_cache = sorted(
                    [{"id": v["ShortName"], "locale": v["Locale"], "gender": v["Gender"]} for v in vs],
                    key=lambda v: (not v["locale"].startswith("en"), v["locale"], v["id"]))
            except Exception:
                return []
        return _voices_cache


def featured():
    return [{"id": i, "label": l} for i, l in FEATURED]


def _rate(speed: float) -> str:
    pct = int(round((float(speed) - 1.0) * 100))
    return f"{pct:+d}%"


async def _synth(text, voice, out_path, speed, pitch):
    com = edge_tts.Communicate(text, voice, rate=_rate(speed), pitch=f"{int(pitch):+d}Hz", boundary="WordBoundary")
    words = []
    with open(out_path, "wb") as f:
        async for chunk in com.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                st = chunk["offset"] / 1e7
                words.append({"start": round(st, 3), "end": round(st + chunk["duration"] / 1e7, 3), "word": chunk["text"]})
    return words


EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]+")


def clean_text(text: str) -> str:
    text = EMOJI.sub("", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def synthesize(text, voice, out_path, speed=1.0, pitch=0, retries=3):
    """Write MP3 to out_path. Returns word timings [{start,end,word}]."""
    text = clean_text(text)
    if not text:
        raise ValueError("Empty text for TTS")
    last = None
    for _ in range(retries):
        try:
            words = _run(_synth(text, voice, str(out_path), speed, pitch))
            _attach_punctuation(text, words)
            return words
        except Exception as e:  # network hiccups
            last = e
    raise RuntimeError(f"TTS failed (edge-tts needs internet): {last}")


def _attach_punctuation(text, words):
    """Edge returns bare words; re-attach trailing punctuation from the source for nicer captions."""
    pos = 0
    for w in words:
        i = text.find(w["word"], pos)
        if i < 0:
            continue
        j = i + len(w["word"])
        while j < len(text) and text[j] in ".,!?;:'\")…":
            j += 1
        w["word"] = text[i:j]
        pos = j

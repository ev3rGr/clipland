"""Video links: recognise the site, read metadata, and download with yt-dlp (supports 1800+ sites)."""
import json
import re
import subprocess
import sys
import time
import uuid
from urllib.parse import parse_qs, urlparse

from .config import DATA, UPLOADS, BACKGROUNDS, MUSIC, WORK
from .media import safe_name

# (id, label, icon, host regex, clip/short regex on the path)
SOURCES = [
    ("youtube", "YouTube", "▶️", r"(^|\.)(youtube\.com|youtu\.be|youtube-nocookie\.com)$", r"^/shorts/"),
    ("twitch", "Twitch", "🟣", r"(^|\.)twitch\.tv$", r"(/clip/|^/clips?\.|clips\.twitch)"),
    ("kick", "Kick", "🟢", r"(^|\.)kick\.com$", r"/clips?/"),
    ("tiktok", "TikTok", "🎵", r"(^|\.)tiktok\.com$", r"."),
    ("x", "X / Twitter", "𝕏", r"(^|\.)(twitter\.com|x\.com)$", r"."),
    ("instagram", "Instagram", "📸", r"(^|\.)instagram\.com$", r"/reels?/"),
    ("facebook", "Facebook", "📘", r"(^|\.)(facebook\.com|fb\.watch)$", r"/reel/"),
    ("reddit", "Reddit", "👽", r"(^|\.)(reddit\.com|redd\.it)$", r"."),
    ("vimeo", "Vimeo", "🎞️", r"(^|\.)vimeo\.com$", None),
    ("streamable", "Streamable", "📼", r"(^|\.)streamable\.com$", r"."),
    ("medal", "Medal", "🏅", r"(^|\.)medal\.tv$", r"."),
    ("rumble", "Rumble", "📺", r"(^|\.)rumble\.com$", None),
    ("dailymotion", "Dailymotion", "📺", r"(^|\.)(dailymotion\.com|dai\.ly)$", None),
    ("drive", "Google Drive", "📁", r"(^|\.)drive\.google\.com$", None),
    ("dropbox", "Dropbox", "📦", r"(^|\.)dropbox\.com$", None),
]
DIRECT_EXT = (".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".mp3", ".m4a", ".wav")
QUALITIES = {"2160": 2160, "1440": 1440, "1080": 1080, "720": 720, "480": 480}
IMPORTS = DATA / "imports.json"


def detect(url: str) -> dict:
    """Instant, offline guess of where a link points."""
    url = (url or "").strip()
    if not re.match(r"^https?://", url, re.I):
        if re.match(r"^[\w.-]+\.[a-z]{2,}(/|$)", url, re.I):
            url = "https://" + url
        else:
            return {"ok": False, "error": "Not a link"}
    u = urlparse(url)
    host = (u.hostname or "").lower()
    path = u.path or "/"
    for sid, label, icon, host_re, short_re in SOURCES:
        if re.search(host_re, host):
            short = bool(short_re and (re.search(short_re, path) or re.search(short_re, host)))
            kind = "short" if short else "video"
            if sid == "twitch":
                kind = "clip" if short else ("vod" if "/videos/" in path else ("live" if path.strip("/") and "/" not in path.strip("/") else "video"))
            if sid == "kick" and short:
                kind = "clip"
            elif sid == "kick" and "/video" not in path:
                kind = "live" if path.strip("/") and "/" not in path.strip("/") else kind
            if sid == "youtube" and "list" in parse_qs(u.query) and "v" not in parse_qs(u.query):
                kind = "playlist"
            elif sid == "youtube" and re.match(r"^/(@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+)(/(videos|shorts|streams|featured))?/?$", path):
                kind = "channel"
            elif sid == "twitch" and re.match(r"^/[^/]+/(videos|clips)/?$", path):
                kind = "channel"
            elif sid == "kick" and re.match(r"^/[^/]+/(videos|clips)/?$", path):
                kind = "channel"
            elif sid == "tiktok" and re.match(r"^/@[^/]+/?$", path):
                kind = "channel"
            return {"ok": True, "url": _normalise(sid, url), "source": sid, "label": label, "icon": icon, "kind": kind}
    if path.lower().endswith(DIRECT_EXT):
        return {"ok": True, "url": url, "source": "direct", "label": "Direct file", "icon": "🔗", "kind": "video"}
    return {"ok": True, "url": url, "source": "other", "label": host or "Website", "icon": "🌐", "kind": "video"}


def _normalise(sid, url):
    if sid == "dropbox":  # share link -> direct download
        url = re.sub(r"([?&])dl=0", r"\1dl=1", url)
        if "dl=1" not in url and "raw=1" not in url:
            url += ("&" if "?" in url else "?") + "dl=1"
    return url


def info(url: str, timeout=40) -> dict:
    """Title, duration, thumbnail... via yt-dlp (no download)."""
    d = detect(url)
    if not d.get("ok"):
        raise ValueError(d["error"])
    if d["kind"] in ("playlist", "channel"):
        raise ValueError("That's a playlist or channel link. Use the batch list to pick videos.")
    try:
        out = subprocess.run([sys.executable, "-m", "yt_dlp", "-J", "--no-playlist", "--no-warnings", "--skip-download", d["url"]],
                             capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {**d, "title": None, "warning": "Couldn't read the video details in time. You can still try downloading."}
    if out.returncode != 0:
        msg = (out.stderr.strip().splitlines() or ["unknown error"])[-1].replace("ERROR: ", "")
        raise ValueError(_friendly(msg))
    j = json.loads(out.stdout)
    if j.get("_type") == "playlist" and j.get("entries"):
        j = next((e for e in j["entries"] if e), j)
    heights = sorted({f.get("height") for f in j.get("formats") or [] if f.get("height") and f.get("vcodec") not in (None, "none")})
    return {**d, "title": j.get("title"), "duration": j.get("duration"), "thumbnail": j.get("thumbnail"),
            "uploader": j.get("uploader") or j.get("channel"), "is_live": bool(j.get("is_live")),
            "max_height": heights[-1] if heights else None, "extractor": j.get("extractor_key"),
            "already": _existing(d["url"])}


def playlist(url: str, limit=200, timeout=90) -> dict:
    """Videos of a playlist / channel page (flat listing: fast, no per-video requests)."""
    d = detect(url)
    if not d.get("ok"):
        raise ValueError(d["error"])
    try:
        out = subprocess.run([sys.executable, "-m", "yt_dlp", "-J", "--flat-playlist", "--yes-playlist", "--no-warnings",
                              "--playlist-end", str(limit), d["url"]], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ValueError("Reading the list took too long. Try a smaller playlist or paste the video links.")
    if out.returncode != 0:
        msg = (out.stderr.strip().splitlines() or ["unknown error"])[-1].replace("ERROR: ", "")
        raise ValueError(_friendly(msg))
    j = json.loads(out.stdout)
    entries = []

    def walk(items):  # channel pages can nest tabs (Videos / Shorts / Live)
        for e in items or []:
            if not e:
                continue
            if e.get("_type") == "playlist" and e.get("entries"):
                walk(e["entries"])
                continue
            link = e.get("webpage_url") or e.get("url")
            if not link:
                continue
            if not link.startswith("http") and e.get("ie_key") == "Youtube":
                link = f"https://www.youtube.com/watch?v={link}"
            thumbs = e.get("thumbnails") or []
            entries.append({"url": link, "title": e.get("title") or link, "duration": e.get("duration"),
                            "thumbnail": e.get("thumbnail") or (thumbs[-1]["url"] if thumbs else None),
                            "is_live": e.get("live_status") == "is_live", "already": _existing(link)})
    walk(j.get("entries") if j.get("_type") == "playlist" else [j])
    seen, uniq = set(), []
    for e in entries:
        if e["url"] not in seen:
            seen.add(e["url"]); uniq.append(e)
    return {**d, "title": j.get("title"), "uploader": j.get("uploader") or j.get("channel"), "entries": uniq[:limit],
            "truncated": len(uniq) >= limit}


def _friendly(msg):
    m = msg.lower()
    if "private" in m:
        return "This video is private."
    if "sign in" in m or "login" in m or "age" in m and "confirm" in m:
        return "This video needs a login (age-restricted or members-only), so it can't be downloaded here."
    if "unsupported url" in m:
        return "This site isn't supported. Try a direct link to the video file."
    if "not available" in m or "unavailable" in m or "removed" in m or "404" in m:
        return "This video isn't available (removed, region-locked or wrong link)."
    if "is offline" in m or "not currently live" in m:
        return "That channel isn't live. Paste a VOD or clip link instead."
    msg = re.sub(r"^(ERROR:\s*)?(\[[\w:]+\]\s*[\w-]+:\s*)?", "", msg.strip())
    return msg[:300]


def _load_imports():
    try:
        return json.loads(IMPORTS.read_text())
    except Exception:
        return {}


def _existing(url, kind="uploads", section=None):
    rec = _load_imports().get(f"{kind}|{url}|{section or ''}")
    if rec and (DATA / rec).exists():
        return rec
    return None


def _remember(url, kind, section, ref):
    d = _load_imports()
    d[f"{kind}|{url}|{section or ''}"] = ref
    IMPORTS.write_text(json.dumps(d, indent=1))


def _ts(v):
    """'1:02:03' / '62:03' / '3723' -> seconds"""
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    parts = [float(p) for p in str(v).strip().split(":")]
    s = 0.0
    for p in parts:
        s = s * 60 + p
    return s


def download(job, url, kind="uploads", quality="1080", start=None, end=None):
    d = detect(url)
    if not d.get("ok"):
        raise ValueError(d["error"])
    url = d["url"]
    dest = {"uploads": UPLOADS, "backgrounds": BACKGROUNDS, "music": MUSIC}[kind]
    s, e = _ts(start), _ts(end)
    section = f"{s or 0:.0f}-{e:.0f}" if e else (f"{s:.0f}-inf" if s else None)
    prev = _existing(url, kind, section)
    if prev:
        job.update(1.0, "Already downloaded")
        return {"file": prev, "reused": True, "source": d, "outputs": []}

    wd = WORK / job.id
    wd.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "yt_dlp", "--no-playlist", "--newline", "--no-warnings", "--no-mtime",
           "--concurrent-fragments", "4", "-o", str(wd / "%(title).80s [%(id)s].%(ext)s")]
    if kind == "music":
        cmd += ["-f", "bestaudio/best", "-x", "--audio-format", "mp3"]
    else:
        hmax = QUALITIES.get(str(quality), 1080)
        # prefer H.264/AAC (fast to decode and edit), capped at the chosen resolution
        cmd += ["-f", "bv*+ba/b", "-S", f"res:{hmax},vcodec:h264,acodec:m4a", "--merge-output-format", "mp4"]
    if section:
        cmd += ["--download-sections", f"*{s or 0}-{e if e else 'inf'}", "--force-keyframes-at-cuts"]
    label = f"{d['icon']} {d['label']}"
    job.update(0.02, f"{label}: starting download")
    proc = subprocess.Popen(cmd + [url], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    tail, stage, last = [], 0, 0.0
    try:
        for line in proc.stdout:
            line = line.strip()
            if line:
                tail = (tail + [line])[-10:]
            if job.cancel_requested:
                proc.kill()
                break
            if line.startswith("[download] Destination"):
                stage += 1  # video, then audio stream
            m = re.search(r"\[download\]\s+([\d.]+)%(?:.*?at\s+(\S+))?(?:.*?ETA\s+(\S+))?", line)
            if m and time.time() - last > 0.5:
                last = time.time()
                pct = float(m.group(1))
                span = (0.02, 0.75) if stage <= 1 else (0.75, 0.93)
                extra = " · ".join(x for x in (m.group(2), m.group(3) and "ETA " + m.group(3)) if x and "Unknown" not in x)
                job.update(span[0] + (span[1] - span[0]) * pct / 100,
                           f"{label}: downloading {'audio ' if stage > 1 else ''}{pct:.0f}%" + (f" · {extra}" if extra else ""))
            elif "[Merger]" in line or "[ExtractAudio]" in line or "[VideoConvertor]" in line:
                job.update(0.94, f"{label}: merging")
    finally:
        rc = proc.wait()
    if job.cancel_requested:
        from .jobs import JobCancelled
        raise JobCancelled()
    if rc != 0:
        err = next((l for l in reversed(tail) if "ERROR" in l), tail[-1] if tail else "unknown error")
        raise RuntimeError("Download failed: " + _friendly(err.replace("ERROR: ", "")))
    files = [f for f in wd.iterdir() if f.suffix.lower() in DIRECT_EXT and not f.name.endswith(".part")]
    if not files:
        raise RuntimeError("Download produced no media file")
    src = max(files, key=lambda f: f.stat().st_size)
    name = f"{uuid.uuid4().hex[:6]}_{safe_name(src.name)}"
    src.rename(dest / name)
    ref = f"{kind}/{name}"
    _remember(url, kind, section, ref)
    try:
        from .media import probe, thumbnail
        meta = probe(dest / name)
        if meta.get("has_video"):
            (WORK / "thumbs").mkdir(exist_ok=True)
            thumbnail(dest / name, WORK / "thumbs" / f"{kind}_{(dest / name).stem}.jpg", t=min(2.0, meta["duration"] / 3))
    except Exception as ex:
        print("thumbnail skipped:", ex)
    return {"file": ref, "source": d, "outputs": []}

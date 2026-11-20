"""AutoClip: long video -> best moments -> vertical clips.

Engines depend on the content type (see presets.py):
  transcript - podcasts/interviews: transcript + LLM pick what is *said*
  signals    - gameplay, streams, trailers, other: game audio, motion, scene cuts, streamer reactions,
               then (optionally) an AI looks at contact sheets of each candidate and ranks/titles them
"""
import hashlib

from PIL import Image, ImageDraw

from .. import jobs, transcribe, moments, reframe, captions, llm, settings, signals, presets
from ..config import WORK, resolve_file, W, H
from ..media import run, probe, venc, AENC, MP4_FLAGS, ass_filter
from .common import out_path, output_entry, work_dir, save_json, load_json, write_srt
from .render_images import font


def _cache_key(path):
    st = path.stat()
    sig = transcribe.signature()
    return hashlib.sha1(f"{path.name}:{st.st_size}:{st.st_mtime_ns}:{sig}".encode()).hexdigest()[:16]


def _cleanup(words, job=None, msg=None):
    """Optionally let the selected LLM fix transcription mistakes before burning captions."""
    if not words or not settings.get()["features"]["caption_cleanup"] or not llm.available():
        return words
    if job and msg:
        job.update(None, msg)
    try:
        return llm.fix_caption_words(words)
    except Exception as e:
        print("caption cleanup skipped:", e)
        return words


def get_transcript(path, job, p0, p1, language=None, duration=None):
    cache = WORK / f"transcript_{_cache_key(path)}.json"
    if cache.exists():
        return load_json(cache)
    wav = work_dir(job) / "audio.wav"
    job.update(p0, "Extracting audio")
    run(["ffmpeg", "-i", path, "-vn", "-ac", "1", "-ar", "16000", wav])
    t = transcribe.transcribe(wav, job, p0, p1, language=language, duration=duration)
    save_json(cache, t)
    transcribe.unload()  # analysis/rendering that follows doesn't need Whisper: give the VRAM back
    return t


def cached_transcript(path):
    cache = WORK / f"transcript_{_cache_key(path)}.json"
    return load_json(cache) if cache.exists() else None


def find_facecam(path, info, mode="auto", rect=None, job=None, p=None):
    """mode: auto | manual | <corner>. rect (manual) is [x, y, w, h] as fractions of the source frame."""
    sw, sh = info["width"], info["height"]
    if mode == "manual" and rect and len(rect) == 4:
        x, y, w, h = [float(v) for v in rect]
        return {"rect": [int(x * sw) // 2 * 2, int(y * sh) // 2 * 2, int(w * sw) // 2 * 2, int(h * sh) // 2 * 2],
                "corner": "manual"}
    if mode in reframe.CORNERS:
        return {"rect": reframe.corner_rect(mode, sw, sh), "corner": mode}
    st = path.stat()
    cache = WORK / f"facecam_{hashlib.sha1(f'{path.name}:{st.st_size}:{st.st_mtime_ns}:v2'.encode()).hexdigest()[:16]}.json"
    if cache.exists():
        return load_json(cache).get("facecam")
    if job:
        job.update(p, "Looking for the facecam")
    fc = reframe.detect_facecam(path, info["duration"], sw, sh)
    save_json(cache, {"facecam": fc})
    return fc


def _hashtags_for(game):
    if not game:
        return ["#fyp", "#viral", "#clips"]
    g = game.replace(" ", "")
    tags = [f"#{g}", "#gaming", "#gameplay", "#fyp"]
    if g.lower() in ("gta6", "gtavi", "gta"):
        tags = ["#GTA6", "#GTAVI", "#GTA", "#Rockstar", "#gaming", "#fyp"]
    return tags


REASON_TITLES = {"impacts / gunfire": ["This gunfight got crazy", "Bullets everywhere", "Wildest shootout"],
                 "loud action": ["Absolute chaos", "This went so wrong", "Pure mayhem"],
                 "fast action": ["Wildest chase ever", "Full send", "No brakes"],
                 "rapid cuts": ["This scene is unreal", "Look at this detail", "Insane scene"],
                 "explosions / flashes": ["Biggest explosion yet", "It all blew up", "Boom"],
                 "big reaction": ["He did NOT expect that", "His reaction", "Lost it"],
                 "steady action": ["Watch till the end", "Wait for it", "Don't skip this"]}


def _contact_sheet(path, start, end, out, n=6, tile_w=384):
    """3x2 grid of frames across [start, end] with timestamps, for the AI to look at."""
    tiles = []
    for k in range(n):
        t = start + (end - start) * (k + 0.5) / n
        frame = out.parent / f"{out.stem}_{k}.jpg"
        try:
            run(["ffmpeg", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1", "-vf", f"scale={tile_w}:-2", "-q:v", "4", frame])
            tiles.append((t, Image.open(frame).convert("RGB")))
        except Exception:
            continue
    if not tiles:
        return None
    tw, th = tiles[0][1].size
    cols = 3
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * th), "black")
    d = ImageDraw.Draw(sheet)
    f = font("Inter-Bold", 22)
    for i, (t, img) in enumerate(tiles):
        x, y = (i % cols) * tw, (i // cols) * th
        sheet.paste(img.resize((tw, th)), (x, y))
        label = f"{int(t // 60)}:{t % 60:04.1f}"
        d.rectangle((x, y, x + 12 + d.textlength(label, font=f), y + 32), fill=(0, 0, 0))
        d.text((x + 6, y + 4), label, font=f, fill=(255, 255, 0))
    sheet.save(out, quality=82)
    return out


def _excerpt(transcript, start, end, limit=400):
    if not transcript:
        return ""
    words = transcribe.all_words(transcript, start, end)
    return " ".join(w["word"] for w in words)[:limit]


# ---------------- analysis ----------------

def analyze(job, file, content_type="podcast", config=None, **legacy):
    """legacy kwargs (count, min_len, max_len, use_ai, language) are merged into config."""
    path = resolve_file(file)
    info = probe(path)
    ctype_def, cfg = presets.resolve(content_type, {**{k: v for k, v in legacy.items() if v is not None}, **(config or {})})
    base = {"file": file, "duration": info["duration"], "width": info.get("width"), "height": info.get("height"),
            "content_type": content_type, "config": cfg}
    if ctype_def["engine"] == "transcript":
        if not info["has_audio"]:
            raise ValueError("This video has no audio track. Pick 'Gameplay' or 'Trailer' instead of Podcast.")
        t = get_transcript(path, job, 0.02, 0.6, cfg.get("language"), info["duration"])
        job.update(0.62, "Finding the best moments")
        ms = moments.find_moments(t, path, info["duration"], float(cfg["min_len"]), float(cfg["max_len"]),
                                  int(cfg["count"]), cfg["use_ai"], job)
        return {**base, "language": t["language"], "moments": ms,
                "transcript": [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in t["segments"]]}
    return {**base, **_analyze_signals(job, path, info, cfg, content_type)}


def _analyze_signals(job, path, info, cfg, content_type):
    dur = info["duration"]
    transcript = None
    if cfg.get("transcribe") and info["has_audio"]:
        transcript = get_transcript(path, job, 0.02, 0.35, cfg.get("language"), dur)
    p_sig = 0.37 if transcript else 0.03
    sig = signals.analyze(path, dur, job, p_sig, 0.72)
    job.update(0.73, "Scoring highlights")
    min_len, max_len = float(cfg["min_len"]), min(float(cfg["max_len"]), dur)
    count = int(cfg["count"])
    cands = signals.highlights(sig, dur, cfg["weights"], min_len, max_len, count, transcript, bool(cfg.get("snap_cuts")))
    if not cands:  # very short or silent input: one clip from the start
        cands = [{"start": 0.0, "end": round(min(dur, max_len), 2), "peak": 0, "score": 60, "reason": "steady action", "signals": {}}]

    facecam = None
    if cfg.get("layout") == "facecam":
        facecam = find_facecam(path, info, cfg.get("facecam", "auto"), cfg.get("facecam_rect"), job, 0.76)

    game = (cfg.get("game") or "").strip()
    picked = None
    source = "signals"
    if cfg.get("use_ai") and llm.available():
        top = cands[: min(len(cands), max(count + 4, int(count * 1.8)), 14)]
        images = None
        if cfg.get("vision") and llm.supports_vision():
            wd = work_dir(job)
            images = []
            for i, c in enumerate(top):
                job.update(0.78 + 0.07 * i / len(top), f"Making preview sheets {i + 1}/{len(top)}")
                images.append(_contact_sheet(path, c["start"], c["end"], wd / f"sheet_{i:02d}.jpg"))
            if any(im is None for im in images):
                images = None
        items = [{"index": i, "start": c["start"], "end": c["end"], "reason": c["reason"],
                  "transcript": _excerpt(transcript, c["start"], c["end"])} for i, c in enumerate(top)]
        provider, model = llm.current()
        job.update(0.86, f"{llm.PROVIDER_LABELS.get(provider, provider)} is {'watching' if images else 'reviewing'} the highlights")
        try:
            ranked = llm.rank_highlights(items, count, content_type, game, images)
            picked = []
            for r in sorted(ranked, key=lambda r: -int(r.get("score", 0) or 0)):
                i = r.get("index")
                if not isinstance(i, int) or not (0 <= i < len(top)) or not r.get("keep", True):
                    continue
                c = dict(top[i])
                tags = [t if str(t).startswith("#") else "#" + str(t) for t in (r.get("hashtags") or [])]
                c.update(score=int(r.get("score", c["score"])), title=str(r.get("title", ""))[:80],
                         reason=str(r.get("reason", c["reason"]))[:240], description=str(r.get("description", ""))[:400],
                         hashtags=[t.replace(" ", "") for t in tags][:8])
                if all(c["end"] <= p["start"] or c["start"] >= p["end"] for p in picked):
                    picked.append(c)
                if len(picked) >= count:
                    break
            source = f"{model}{' + vision' if images else ''}"
            if not picked:
                picked = None
        except Exception as e:
            print("AI highlight ranking failed:", e)
            job.update(None, f"AI unavailable ({str(e)[:60]}), using signal scores")
    if picked is None:
        picked = cands[:count]
        for i, c in enumerate(picked):
            parts = c["reason"].split(" + ")
            key = parts[1] if len(parts) > 1 and parts[0] == "loud action" else parts[0]
            options = REASON_TITLES.get(key, REASON_TITLES["steady action"])
            phrase = options[i % len(options)]
            c.update(title=f"{phrase} in {game}" if game else phrase, description="", hashtags=_hashtags_for(game))
    out = []
    for i, c in enumerate(sorted(picked, key=lambda c: -c["score"]), 1):
        out.append({"id": i, "start": c["start"], "end": c["end"], "score": c["score"], "title": c.get("title", ""),
                    "reason": c["reason"], "description": c.get("description", ""), "hashtags": c.get("hashtags", []),
                    "source": source, "peak": c.get("peak"),
                    "text": _excerpt(transcript, c["start"], c["end"], 300) or f"Detected: {c['reason']}"})
    return {"moments": out, "facecam": facecam, "has_transcript": transcript is not None}


# ---------------- rendering ----------------

def _plan(path, info, start, end, layout, opts):
    sw, sh = info["width"], info["height"]
    if layout in ("zoom", "fit", "center"):
        return {"mode": layout}
    if layout == "facecam":
        return {"mode": "facecam", "rect": (opts.get("facecam") or {}).get("rect"),
                "size": opts.get("facecam_size", "medium"), "gameplay_fit": opts.get("gameplay_fit", "crop"),
                "cam_fit": opts.get("facecam_fit", "blur"), "cam_pos": opts.get("facecam_pos", "top")}
    return reframe.analyze(path, start, end, sw, sh, layout)


def _title_margin(plan):
    """Keep the hook title off faces: on the facecam/gameplay seam, or the gap between split halves."""
    if plan.get("mode") == "facecam" and plan.get("rect"):
        cam_h = reframe.facecam_height(plan, H)
        seam = H - cam_h if plan.get("cam_pos") == "bottom" else cam_h
        return max(20, seam - 50)
    return None


CAPTION_IN_GAME = {"top": 0.14, "upper": 0.3, "middle": 0.5, "lower": 0.72, "bottom": 0.88}


def _caption_y(plan, position):
    """With a facecam band, keep captions inside the gameplay part instead of over the streamer."""
    if plan.get("mode") == "facecam" and plan.get("rect"):
        y0, y1 = reframe.game_area(plan, H)
        frac = CAPTION_IN_GAME.get(position, 0.72)
        if plan.get("cam_pos") != "bottom":  # leave room for the hook title on the seam
            frac = max(frac, 0.3)
        return (y0 + (y1 - y0) * frac) / H
    return None


def render_clip(job, path, info, clip, idx, style, position, layout, title_mode, highlight, p0, p1,
                transcript=None, opts=None):
    opts = opts or {}
    start, end = float(clip["start"]), float(clip["end"])
    dur = end - start
    wd = work_dir(job)
    words = []
    if style != "none" and info["has_audio"]:
        if transcript is not None:
            words = transcribe.all_words(transcript, start, end)
        else:  # no prior transcript: transcribe just this range
            wav = wd / f"clip{idx}.wav"
            run(["ffmpeg", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", path, "-vn", "-ac", "1", "-ar", "16000", wav])
            t = transcribe.transcribe(wav, job, p0, p0 + (p1 - p0) * 0.3)
            words = transcribe.all_words(t)
        words = _cleanup(words, job, f"Clip {idx}: polishing captions with AI")
    sw, sh = info["width"], info["height"]
    job.update(p0 + (p1 - p0) * 0.3, f"Clip {idx}: framing")
    plan = _plan(path, info, start, end, layout, opts)
    vf = f"[0:v]{reframe.plan_filter(plan, sw, sh, wd)}"
    title = (clip.get("title") or "").strip()
    if words or (title and title_mode != "none"):
        ass = wd / f"clip{idx}.ass"
        captions.build_ass(words, ass, style if style != "none" else "bold", position,
                           title=title if title_mode != "none" else None,
                           title_until=(min(4.0, dur) if title_mode == "intro" else dur), highlight=highlight,
                           title_margin=_title_margin(plan), y_frac=_caption_y(plan, position))
        vf += f",{ass_filter(ass)}"
    vf += "[v]"
    out = out_path(job, f"clip{idx}")
    cmd = ["ffmpeg", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", path, "-filter_complex", vf, "-map", "[v]"]
    if info["has_audio"]:
        cmd += ["-map", "0:a:0", *AENC, "-af", "loudnorm=I=-14:TP=-1.5:LRA=11"]
    cmd += [*venc(), "-r", "30", *MP4_FLAGS, out]
    run(cmd, job, dur, p0 + (p1 - p0) * 0.4, p1, f"Rendering clip {idx}")
    srt = out.with_suffix(".srt")
    if words:
        write_srt(words, srt)
    framing = plan.get("mode", "center") + (" + split" if plan.get("split") else "")
    return output_entry(out, title or f"Clip {idx}", score=clip.get("score"), start=start, end=end,
                        srt=f"outputs/{srt.name}" if words else None, framing=framing,
                        description=clip.get("description", ""), hashtags=clip.get("hashtags", []),
                        reason=clip.get("reason"), text=(clip.get("text") or "")[:600] or None, engine=clip.get("source"))


def render(job, file, clips, style="bold", position="lower", reframe_mode="auto", title_mode="intro",
           highlight=None, p0=0.0, p1=1.0, content_type=None, facecam=None, facecam_mode="auto",
           facecam_size="medium", gameplay_fit="crop", facecam_rect=None, facecam_fit="blur", facecam_pos="top",
           **_ignored):
    path = resolve_file(file)
    info = probe(path)
    if not info.get("has_video"):
        raise ValueError("Not a video file")
    if not clips:
        raise ValueError("No clips selected")
    transcript = cached_transcript(path) if style != "none" else None
    if reframe_mode == "facecam" and (facecam_mode == "manual" or not (facecam and facecam.get("rect"))):
        facecam = find_facecam(path, info, facecam_mode, facecam_rect, job, p0)
    opts = {"facecam": facecam, "facecam_size": facecam_size, "gameplay_fit": gameplay_fit,
            "facecam_fit": facecam_fit, "facecam_pos": facecam_pos}
    outs = []
    n = len(clips)
    for i, clip in enumerate(clips, 1):
        a = p0 + (p1 - p0) * (i - 1) / n
        b = p0 + (p1 - p0) * i / n
        job.update(a, f"Clip {i}/{n}")
        outs.append(render_clip(job, path, info, clip, i, style, position, reframe_mode, title_mode, highlight, a, b,
                                transcript, opts))
    return {"outputs": outs}


def _render_opts(cfg, analysis=None):
    return {"style": cfg.get("style", "bold"), "position": cfg.get("position", "lower"),
            "reframe_mode": cfg.get("layout", "auto"), "title_mode": cfg.get("title_mode", "intro"),
            "facecam": (analysis or {}).get("facecam"), "facecam_mode": cfg.get("facecam", "auto"),
            "facecam_size": cfg.get("facecam_size", "medium"), "gameplay_fit": cfg.get("gameplay_fit", "crop"),
            "facecam_rect": cfg.get("facecam_rect"), "facecam_fit": cfg.get("facecam_fit", "blur"),
            "facecam_pos": cfg.get("facecam_pos", "top")}


def layout_preview(file, t=None, out=None, **opts):
    """Render one 9:16 frame with the given layout options (for the settings preview)."""
    path = resolve_file(file)
    info = probe(path)
    t = float(t if t is not None else min(info["duration"] * 0.3, 60))
    layout = opts.get("layout", "facecam")
    plan_opts = {k: opts.get(k) for k in ("facecam_size", "gameplay_fit", "facecam_fit", "facecam_pos") if opts.get(k)}
    if layout == "facecam":
        plan_opts["facecam"] = find_facecam(path, info, opts.get("facecam", "auto"), opts.get("facecam_rect"))
    plan = _plan(path, info, t, t + 1, layout, plan_opts) if layout in ("facecam", "zoom", "fit", "center") \
        else {"mode": "zoom"}
    vf = f"[0:v]{reframe.plan_filter(plan, info['width'], info['height'], WORK)},scale=540:960[v]"
    run(["ffmpeg", "-ss", f"{t:.2f}", "-i", path, "-filter_complex", vf, "-map", "[v]", "-frames:v", "1", "-q:v", "3", out])
    return plan_opts.get("facecam")


@jobs.handler("analyze")
def analyze_job(job, **p):
    return analyze(job, **p)


@jobs.handler("render_clips")
def render_job(job, file, clips, **p):
    return render(job, file, clips, **p)


@jobs.handler("autoclip")
def autoclip_job(job, file, content_type="podcast", config=None, **legacy):
    render_keys = {"style", "position", "reframe_mode", "title_mode"}
    legacy_cfg = {k: v for k, v in legacy.items() if k not in render_keys}
    if "reframe_mode" in legacy:
        legacy_cfg["layout"] = legacy["reframe_mode"]
    for k in ("style", "position", "title_mode"):
        if k in legacy:
            legacy_cfg[k] = legacy[k]
    res = analyze(job, file, content_type, {**legacy_cfg, **(config or {})})
    job.update(0.9 if res["content_type"] != "podcast" else 0.7, "Rendering clips")
    out = render(job, file, res["moments"], p0=0.9 if res["content_type"] != "podcast" else 0.7, p1=1.0,
                 **_render_opts(res["config"], res))
    return {**res, **out}


@jobs.handler("captions")
def captions_job(job, file, style="bold", position="lower", layout="keep", language=None, highlight=None, size_scale=1.0):
    """Auto-subtitle any video. layout: keep | auto | face | fit | center | zoom"""
    path = resolve_file(file)
    info = probe(path)
    t = get_transcript(path, job, 0.02, 0.55, language, info["duration"])
    words = _cleanup(transcribe.all_words(t), job, "Polishing captions with AI")
    wd = work_dir(job)
    sw, sh = info["width"], info["height"]
    if layout == "keep":
        ow, oh = sw - sw % 2, sh - sh % 2
        chain = f"[0:v]scale={ow}:{oh},setsar=1"
    else:
        ow, oh = W, H
        job.update(0.56, "Framing")
        plan = _plan(path, info, 0, info["duration"], layout, {})
        chain = f"[0:v]{reframe.plan_filter(plan, sw, sh, wd)}"
    ass = wd / "subs.ass"
    captions.build_ass(words, ass, style, position, width=ow, height=oh, highlight=highlight, size_scale=size_scale)
    out = out_path(job, "captioned")
    run(["ffmpeg", "-i", path, "-filter_complex", f"{chain},{ass_filter(ass)}[v]", "-map", "[v]", "-map", "0:a:0?",
         *AENC, *venc(), *MP4_FLAGS, out], job, info["duration"], 0.6, 1.0, "Burning captions")
    srt = out.with_suffix(".srt")
    write_srt(words, srt)
    return {"outputs": [output_entry(out, "Captioned video", srt=f"outputs/{srt.name}")],
            "transcript": " ".join(s["text"] for s in t["segments"])}

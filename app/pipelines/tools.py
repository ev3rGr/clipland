"""Free ffmpeg utilities: trim, compress, gif, speed, reverse, mute, mp3, merge, aspect, volume, enhance..."""
import subprocess
import sys

from .. import jobs
from ..config import UPLOADS, BACKGROUNDS, MUSIC, resolve_file
from ..media import run, probe, venc, AENC, MP4_FLAGS, safe_name
from .common import out_path, output_entry, work_dir

TOOLS = {
    "trim": "Video Trimmer", "compress": "Video Compressor", "gif": "Video to GIF", "speed": "Speed Changer",
    "reverse": "Video Reverser", "mute": "Mute Video", "mp3": "MP3 Converter", "mp4": "MP4 Converter",
    "merge": "Video Merger", "aspect": "Aspect Ratio Converter", "volume": "Volume Booster",
    "enhance": "Speech Enhancer", "balance": "Audio Balancer", "thumbnail": "Thumbnail Grabber",
}

RATIOS = {"9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350), "16:9": (1920, 1080), "4:3": (1440, 1080)}


def _atempo(factor):
    parts = []
    while factor > 2.0:
        parts.append("atempo=2.0"); factor /= 2.0
    while factor < 0.5:
        parts.append("atempo=0.5"); factor /= 0.5
    parts.append(f"atempo={factor:.4f}")
    return ",".join(parts)


@jobs.handler("tool")
def tool_job(job, tool, file=None, files=None, **o):
    if tool == "merge":
        return _merge(job, files or [], o)
    src = resolve_file(file)
    info = probe(src)
    dur = info["duration"]
    has_v, has_a = info.get("has_video"), info["has_audio"]
    amap = ["-map", "0:a:0?"]

    if tool == "trim":
        s, e = float(o.get("start", 0)), float(o.get("end") or dur)
        out = out_path(job, "trim")
        run(["ffmpeg", "-ss", s, "-to", e, "-i", src, "-map", "0:v:0?", *amap, *venc(), *AENC, *MP4_FLAGS, out],
            job, e - s)
    elif tool == "compress":
        out = out_path(job, "compressed")
        target_mb = float(o.get("target_mb") or 0)
        maxh = int(o.get("max_height") or 1080)
        vf = f"scale=-2:'min({maxh},ih)'"
        if target_mb > 0:
            kbps = max(150, int(target_mb * 8192 / dur - 128))
            vargs = ["-c:v", "libx264", "-preset", "medium", "-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.3)}k",
                     "-bufsize", f"{kbps * 2}k", "-pix_fmt", "yuv420p"]
            aargs = ["-c:a", "aac", "-b:a", "96k"]
        else:
            vargs = ["-c:v", "libx264", "-preset", "medium", "-crf", {"high": 23, "medium": 27, "low": 31}[o.get("quality", "medium")],
                     "-pix_fmt", "yuv420p"]
            aargs = ["-c:a", "aac", "-b:a", "128k"]
        run(["ffmpeg", "-i", src, "-vf", vf, *amap, *vargs, *aargs, *MP4_FLAGS, out], job, dur)
    elif tool == "gif":
        s, e = float(o.get("start", 0)), float(o.get("end") or min(dur, 8))
        fps, width = int(o.get("fps", 12)), int(o.get("width", 480))
        out = out_path(job, "anim", "gif")
        run(["ffmpeg", "-ss", s, "-to", e, "-i", src, "-vf",
             f"fps={fps},scale={width}:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4",
             "-loop", "0", out], job, e - s)
    elif tool == "speed":
        f = max(0.25, min(4.0, float(o.get("factor", 1.5))))
        out = out_path(job, f"speed{f:g}x")
        cmd = ["ffmpeg", "-i", src, "-filter_complex", f"[0:v]setpts=PTS/{f}[v]" + (f";[0:a]{_atempo(f)}[a]" if has_a else ""),
               "-map", "[v]"] + (["-map", "[a]", *AENC] if has_a else []) + [*venc(), *MP4_FLAGS, out]
        run(cmd, job, dur / f)
    elif tool == "reverse":
        if dur > 120:
            raise ValueError("Reverse works on videos up to 2 minutes (it holds every frame in memory). Trim first.")
        out = out_path(job, "reversed")
        run(["ffmpeg", "-i", src, "-vf", "reverse"] + (["-af", "areverse", *AENC] if has_a else []) + [*venc(), *MP4_FLAGS, out], job, dur)
    elif tool == "mute":
        out = out_path(job, "muted")
        run(["ffmpeg", "-i", src, "-an", "-c:v", "copy", *MP4_FLAGS, out])
    elif tool == "mp3":
        if not has_a:
            raise ValueError("No audio track found")
        out = out_path(job, "audio", "mp3")
        run(["ffmpeg", "-i", src, "-vn", "-c:a", "libmp3lame", "-q:a", "2", out], job, dur)
    elif tool == "mp4":
        out = out_path(job, "converted")
        run(["ffmpeg", "-i", src, "-map", "0:v:0?", *amap, *venc(), *AENC, *MP4_FLAGS, out], job, dur)
    elif tool == "aspect":
        ow, oh = RATIOS.get(o.get("ratio", "9:16"), (1080, 1920))
        if o.get("mode", "fit") == "crop":
            vf = f"scale={ow}:{oh}:force_original_aspect_ratio=increase,crop={ow}:{oh},setsar=1"
        else:
            vf = (f"split=2[bg][fg];[bg]scale={ow}:{oh}:force_original_aspect_ratio=increase,crop={ow}:{oh},boxblur=24:2[bgb];"
                  f"[fg]scale={ow}:{oh}:force_original_aspect_ratio=decrease[fgs];[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1")
        out = out_path(job, o.get("ratio", "9x16").replace(":", "x"))
        run(["ffmpeg", "-i", src, "-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]", *amap, *venc(), *AENC, *MP4_FLAGS, out], job, dur)
    elif tool in ("volume", "enhance", "balance"):
        if not has_a:
            raise ValueError("No audio track found")
        af = {
            "volume": f"volume={float(o.get('gain_db', 6))}dB,alimiter=limit=0.97",
            "enhance": "highpass=f=80,lowpass=f=12000,afftdn=nf=-25:tn=1,"
                       "acompressor=threshold=-20dB:ratio=3:attack=5:release=120,loudnorm=I=-16:TP=-1.5:LRA=11",
            "balance": "loudnorm=I=-14:TP=-1.5:LRA=11",
        }[tool]
        if has_v:
            out = out_path(job, tool)
            run(["ffmpeg", "-i", src, "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy", "-af", af, *AENC, *MP4_FLAGS, out], job, dur)
        else:
            out = out_path(job, tool, "mp3")
            run(["ffmpeg", "-i", src, "-af", af, "-c:a", "libmp3lame", "-q:a", "2", out], job, dur)
    elif tool == "thumbnail":
        t = float(o.get("time", dur / 2))
        out = out_path(job, "frame", "jpg")
        run(["ffmpeg", "-ss", t, "-i", src, "-frames:v", "1", "-q:v", "2", out])
    else:
        raise ValueError(f"Unknown tool {tool}")
    return {"outputs": [output_entry(out, TOOLS.get(tool, tool))]}


def _merge(job, files, o):
    if len(files) < 2:
        raise ValueError("Pick at least two videos to merge")
    paths = [resolve_file(f) for f in files]
    infos = [probe(p) for p in paths]
    ow, oh = (infos[0]["width"] - infos[0]["width"] % 2, infos[0]["height"] - infos[0]["height"] % 2)
    inputs, fc, cat = [], [], ""
    for i, (p, inf) in enumerate(zip(paths, infos)):
        inputs += ["-i", p]
        fc.append(f"[{i}:v]scale={ow}:{oh}:force_original_aspect_ratio=decrease,pad={ow}:{oh}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v{i}]")
        if inf["has_audio"]:
            fc.append(f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo[a{i}]")
        else:
            fc.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{inf['duration']:.3f}[a{i}]")
        cat += f"[v{i}][a{i}]"
    fc.append(f"{cat}concat=n={len(paths)}:v=1:a=1[v][a]")
    out = out_path(job, "merged")
    total = sum(i["duration"] for i in infos)
    run(["ffmpeg", *inputs, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]", *venc(), *AENC, *MP4_FLAGS, out], job, total)
    return {"outputs": [output_entry(out, "Merged video")]}


@jobs.handler("import_url")
def import_url_job(job, url, kind="uploads", quality="1080", start=None, end=None):
    """Download a video you have rights to. The site is detected automatically (yt-dlp supports most sites)."""
    from .. import sources
    return sources.download(job, url, kind, quality, start, end)

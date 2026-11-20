"""Keeps what was generated with each export (score, title, description, hashtags, why it was picked…)
in a small JSON file next to it (outputs/<name>.json), so the Library can show it later."""
import json
import time
from pathlib import Path

from .config import JOBS, OUTPUTS

KIND_LABELS = {"autoclip": "AutoClip", "render_clips": "AutoClip", "captions": "Auto captions", "reddit": "Story video",
               "faketext": "Fake texts", "voiceover": "Voiceover", "tool": "Tool"}


def meta_path(out: Path) -> Path:
    return out.with_suffix(".json")


def read(out: Path) -> dict | None:
    try:
        return json.loads(meta_path(out).read_text())
    except Exception:
        return None


def _write(out: Path, data: dict):
    tmp = meta_path(out).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    tmp.replace(meta_path(out))


def save_job_outputs(job, overwrite=True):
    """Called when a job finishes: one metadata file per output."""
    result = job.result or {}
    outs = result.get("outputs") or []
    params = job.params or {}
    source = params.get("file") or result.get("file")
    for o in outs:
        f = o.get("file") or ""
        if not f.startswith("outputs/"):
            continue
        out = OUTPUTS / f.split("/", 1)[1]
        if not out.exists() or (not overwrite and meta_path(out).exists()):
            continue
        data = {k: v for k, v in o.items() if v not in (None, "", [])}
        if o.get("start") is not None:  # fill in what older renders didn't carry (why it was picked, transcript…)
            m = next((m for m in result.get("moments") or [] if abs(float(m.get("start", -99)) - float(o["start"])) < 0.6), None)
            for k, src in (("reason", "reason"), ("text", "text"), ("engine", "source"), ("description", "description"), ("hashtags", "hashtags")):
                if m and not data.get(k) and m.get(src):
                    data[k] = m[src][:600] if isinstance(m[src], str) else m[src]
        data.update({"job_id": job.id, "job_kind": job.kind, "made_with": KIND_LABELS.get(job.kind, job.kind),
                     "created": job.finished or time.time()})
        if source:
            data["source_file"] = source
            data["source_name"] = Path(source).name.split("_", 1)[-1]
        ct = params.get("content_type") or result.get("content_type")
        if ct:
            data["content_type"] = ct
        if job.kind == "tool" and params.get("tool"):
            data["tool"] = params["tool"]
        try:
            _write(out, data)
        except Exception as e:
            print("[archive] could not save metadata for", out.name, e)


def backfill():
    """Exports made before metadata files existed: rebuild them from the saved job history."""
    from types import SimpleNamespace
    for jf in sorted(JOBS.glob("*.json"), key=lambda p: p.stat().st_mtime):
        try:
            j = json.loads(jf.read_text())
        except Exception:
            continue
        if j.get("status") != "done" or not (j.get("result") or {}).get("outputs"):
            continue
        job = SimpleNamespace(id=j.get("id"), kind=j.get("kind"), params=j.get("params") or {},
                              result=j["result"], finished=j.get("finished"))
        save_job_outputs(job, overwrite=False)

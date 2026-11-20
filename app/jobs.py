"""Tiny persistent job queue. Heavy work runs one job at a time (GPU has 4GB)."""
import json
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict

from .config import JOBS


class JobCancelled(Exception):
    pass


@dataclass
class Job:
    id: str
    kind: str
    params: dict
    status: str = "queued"  # queued | running | done | error | cancelled
    progress: float = 0.0
    message: str = "Waiting in queue"
    result: dict = field(default_factory=dict)
    error: str = ""
    created: float = field(default_factory=time.time)
    finished: float = 0.0
    cancel_requested: bool = False

    def update(self, progress=None, message=None):
        if self.cancel_requested:
            raise JobCancelled()
        if progress is not None:
            self.progress = max(0.0, min(1.0, float(progress)))
        if message is not None:
            self.message = message
        save(self)

    def public(self):
        d = asdict(self)
        d.pop("cancel_requested", None)
        return d


_jobs: dict[str, Job] = {}
_lock = threading.Lock()
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="job")
_handlers = {}


def handler(kind):
    def deco(fn):
        _handlers[kind] = fn
        return fn
    return deco


def save(job: Job):
    tmp = JOBS / f"{job.id}.json.tmp"
    tmp.write_text(json.dumps(job.public()))
    tmp.replace(JOBS / f"{job.id}.json")


def load_all():
    for f in sorted(JOBS.glob("*.json")):
        try:
            d = json.loads(f.read_text())
            job = Job(**d)
            if job.status in ("queued", "running"):
                job.status, job.error = "error", "Server restarted while job was running"
                save(job)
            _jobs[job.id] = job
        except Exception:
            pass


def submit(kind: str, params: dict) -> Job:
    if kind not in _handlers:
        raise KeyError(kind)
    job = Job(id=uuid.uuid4().hex[:10], kind=kind, params=params)
    with _lock:
        _jobs[job.id] = job
    save(job)
    _pool.submit(_run, job)
    return job


def _run(job: Job):
    if job.cancel_requested:
        job.status = "cancelled"; save(job); return
    job.status = "running"
    job.update(0.0, "Starting")
    try:
        job.result = _handlers[job.kind](job, **job.params) or {}
        job.status, job.progress, job.message = "done", 1.0, "Done"
    except JobCancelled:
        job.status, job.message = "cancelled", "Cancelled"
    except Exception as e:  # report error to the UI
        traceback.print_exc()
        job.status, job.error = "error", f"{type(e).__name__}: {e}"
        job.message = "Failed"
    job.finished = time.time()
    save(job)


def get(job_id) -> Job | None:
    return _jobs.get(job_id)


def cancel(job_id):
    job = _jobs.get(job_id)
    if job and job.status in ("queued", "running"):
        job.cancel_requested = True
        if job.status == "queued":
            job.status = "cancelled"
            save(job)


def delete(job_id):
    job = _jobs.pop(job_id, None)
    (JOBS / f"{job_id}.json").unlink(missing_ok=True)
    return job


def listing(limit=100):
    return [j.public() for j in sorted(_jobs.values(), key=lambda j: -j.created)[:limit]]

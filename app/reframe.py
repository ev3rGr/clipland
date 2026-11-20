"""Turn horizontal footage into 9:16 by following the person who is talking.

Pipeline:
  1. Decode low-res frames with ffmpeg using the exact same seek as the final render (no timing drift).
  2. Detect faces + landmarks with YuNet (OpenCV DNN). Falls back to Haar cascades if the model is missing.
  3. Track faces across frames, score who is speaking from lip motion (relative to head motion).
  4. Detect scene cuts; pick a subject with hysteresis (no ping-ponging between people).
  5. Smooth camera with a dead zone, hard cuts on speaker switches/scene cuts, rendered with ffmpeg sendcmd.
  6. Two people too far apart to share one 9:16 frame -> optional split screen (one per half).
"""
import subprocess
from pathlib import Path

import cv2
import numpy as np

from .config import ROOT, W, H

YUNET = ROOT / "assets" / "models" / "face_detection_yunet_2023mar.onnx"
SAMPLE_FPS = 8.0
ANALYSIS_W = 640


# ---------------- detection ----------------

class Detector:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.yunet = None
        if YUNET.exists() and hasattr(cv2, "FaceDetectorYN"):
            self.yunet = cv2.FaceDetectorYN.create(str(YUNET), "", (w, h), 0.7, 0.3, 50)
        else:
            self.haar = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

    def __call__(self, frame):
        """Returns list of dicts: x, y, w, h, cx, cy, mouth(x,y,width) or None, eyes(x,y,width) or None."""
        out = []
        if self.yunet is not None:
            _, faces = self.yunet.detect(frame)
            for f in faces if faces is not None else []:
                x, y, w, h = f[:4]
                rex, rey, lex, ley, _, _, rmx, rmy, lmx, lmy = f[4:14]
                mw = float(np.hypot(lmx - rmx, lmy - rmy)) or w * 0.4
                ew = float(np.hypot(lex - rex, ley - rey)) or w * 0.4
                out.append(dict(x=x, y=y, w=w, h=h, cx=x + w / 2, cy=y + h / 2, score=float(f[14]),
                                mouth=((rmx + lmx) / 2, (rmy + lmy) / 2, mw), eyes=((rex + lex) / 2, (rey + ley) / 2, ew)))
        else:
            gray = cv2.equalizeHist(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
            for x, y, w, h in self.haar.detectMultiScale(gray, 1.12, 6, minSize=(28, 28)):
                out.append(dict(x=x, y=y, w=w, h=h, cx=x + w / 2, cy=y + h / 2, score=0.8,
                                mouth=(x + w / 2, y + h * 0.78, w * 0.4), eyes=(x + w / 2, y + h * 0.38, w * 0.4)))
        return out


def _patch(gray, center, width, aspect=0.6, size=(24, 14)):
    cx, cy, = center[0], center[1]
    hw, hh = width * 0.8, width * 0.8 * aspect
    x0, y0, x1, y1 = int(cx - hw), int(cy - hh), int(cx + hw), int(cy + hh)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(gray.shape[1], x1), min(gray.shape[0], y1)
    if x1 - x0 < 4 or y1 - y0 < 3:
        return None
    p = cv2.resize(gray[y0:y1, x0:x1], size, interpolation=cv2.INTER_AREA).astype(np.float32)
    return (p - p.mean()) / (p.std() + 6.0)


def read_frames(path, start, end, sw, sh, fps=SAMPLE_FPS):
    """Yield (t_rel, bgr_frame) decoded by ffmpeg with the same input seek used for rendering."""
    aw = ANALYSIS_W
    ah = int(round(sh * aw / sw / 2)) * 2
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(path),
           "-vf", f"fps={fps},scale={aw}:{ah}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    n = aw * ah * 3
    i = 0
    try:
        while True:
            buf = proc.stdout.read(n)
            if len(buf) < n:
                break
            yield i / fps, np.frombuffer(buf, np.uint8).reshape(ah, aw, 3)
            i += 1
    finally:
        proc.stdout.close()
        proc.wait()


# ---------------- analysis ----------------

def crop_width(src_w, src_h):
    cw = int(round(src_h * W / H / 2)) * 2
    return min(cw, src_w - src_w % 2)


def analyze(path, start, end, sw, sh, mode="auto"):
    """Returns a framing plan dict consumed by plan_filter()."""
    cw = crop_width(sw, sh)
    if sw / sh <= W / H + 0.01:
        return {"mode": "vertical"}
    if mode in ("center", "fit", "zoom"):
        return {"mode": mode}

    scale = sw / ANALYSIS_W
    det = None
    tracks = {}           # id -> state
    next_id = 0
    samples = []          # per-frame: dict(t, cut, faces=[(id, cx_src, w_src, cy_src, speak)])
    prev_small, prev_hist = None, None
    for t, frame in read_frames(path, start, end, sw, sh):
        if det is None:
            det = Detector(frame.shape[1], frame.shape[0])
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # scene-cut detection: big pixel change + colour distribution change
        small = cv2.resize(gray, (64, 36)).astype(np.float32)
        hsv = cv2.cvtColor(cv2.resize(frame, (64, 36)), cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [16, 8], [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        cut = False
        if prev_small is not None:
            mad = float(np.mean(np.abs(small - prev_small)))
            bh = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_BHATTACHARYYA)
            cut = (mad > 30 and bh > 0.15) or bh > 0.45 or mad > 55
        prev_small, prev_hist = small, hist
        if cut:
            tracks = {}
        faces = [f for f in det(frame) if f["w"] >= frame.shape[1] * 0.025]
        # greedy match to tracks by distance
        used = set()
        visible = []
        for f in sorted(faces, key=lambda f: -f["w"]):
            best, best_d = None, 1e9
            for tid, tr in tracks.items():
                if tid in used or t - tr["last"] > 1.5:
                    continue
                d = np.hypot(f["cx"] - tr["cx"], f["cy"] - tr["cy"])
                if d < max(f["w"], tr["w"]) * 0.8 and d < best_d:
                    best, best_d = tid, d
            if best is None:
                best = next_id; next_id += 1
                tracks[best] = {"speak": 0.0, "mouth": None, "eyes": None, "hits": 0}
            tr = tracks[best]
            used.add(best)
            mp = _patch(gray, f["mouth"][:2], f["mouth"][2] * 1.0, aspect=0.55)
            ep = _patch(gray, f["eyes"][:2], f["eyes"][2] * 0.9, aspect=0.4)
            if mp is not None and tr["mouth"] is not None and ep is not None and tr["eyes"] is not None:
                m_motion = float(np.mean(np.abs(mp - tr["mouth"])))
                e_motion = float(np.mean(np.abs(ep - tr["eyes"])))
                raw = max(0.0, m_motion - 0.7 * e_motion)
                tr["speak"] = tr["speak"] * 0.65 + raw * 0.35
            tr.update(cx=f["cx"], cy=f["cy"], w=f["w"], last=t, mouth=mp, eyes=ep, hits=tr["hits"] + 1)
            visible.append((best, f["cx"] * scale, f["w"] * scale, f["cy"] * scale, tr["speak"]))
        samples.append({"t": t, "cut": cut, "faces": visible})

    if not samples or not any(s["faces"] for s in samples):
        return {"mode": "center", "reason": "no faces found"}

    plan = _track_plan(samples, sw, sh, cw)
    if mode in ("auto", "split"):
        _add_split_segments(plan, samples, sw, sh, cw, force=(mode == "split"))
    return plan


def _people(samples, sw):
    """Cluster faces in a list of samples into people by horizontal position."""
    people = []
    for s in samples:
        for f in s["faces"]:
            for p in people:
                if abs(p["cx"] - f[1]) < sw * 0.1:
                    p["fs"].append(f)
                    p["cx"] = float(np.median([g[1] for g in p["fs"]]))
                    break
            else:
                people.append({"cx": f[1], "fs": [f]})
    return sorted(people, key=lambda p: -len(p["fs"]))


def _add_split_segments(plan, samples, sw, sh, cw, force=False):
    """Per camera shot: if two people sit too far apart to share one 9:16 frame, show them stacked."""
    shots, cur = [], []
    for s in samples:
        if s["cut"] and cur:
            shots.append(cur); cur = []
        cur.append(s)
    if cur:
        shots.append(cur)
    segs = []
    for shot in shots:
        people = _people(shot, sw)
        if len(people) < 2:
            continue
        a, b = people[0], people[1]
        need = max(2, int(len(shot) * (0.35 if force else 0.6)))
        if len(a["fs"]) < need or len(b["fs"]) < need:
            continue
        fw = float(np.median([f[2] for f in a["fs"] + b["fs"]]))
        span = abs(a["cx"] - b["cx"]) + fw * 1.6
        if span <= cw * 0.92 and not force:
            continue
        pair = [(float(np.median([f[1] for f in p["fs"]])), float(np.median([f[3] for f in p["fs"]])),
                 float(np.median([f[2] for f in p["fs"]]))) for p in sorted((a, b), key=lambda p: p["cx"])]
        segs.append((shot[0]["t"], shot[-1]["t"] + 1.0 / SAMPLE_FPS, pair))
    if not segs:
        return
    # one fixed half-frame crop size for the whole clip (9:8 = 1080x960 halves); positions vary per shot
    fw = float(np.median([p[2] for _, _, pair in segs for p in pair]))
    bh = min(sh, max(fw * 3.6, sh * 0.42))
    bw = bh * W / (H / 2)
    if bw > sw * 0.55:
        bw = sw * 0.55
        bh = bw * (H / 2) / W
    bw, bh = int(bw) // 2 * 2, int(bh) // 2 * 2
    out = []
    for t0, t1, pair in segs:
        boxes = [(int(np.clip(cx - bw / 2, 0, sw - bw)) // 2 * 2, int(np.clip(cy - bh * 0.4, 0, sh - bh)) // 2 * 2)
                 for cx, cy, _ in pair]
        out.append((round(t0, 3), round(t1, 3), boxes))
    plan["split"] = {"size": (bw, bh), "segments": out}


def _track_plan(samples, sw, sh, cw):
    max_x = sw - cw
    clamp = lambda v: float(np.clip(v, 0, max_x))
    subject, last_switch, challenger, challenger_since = None, -9.0, None, None
    cam = None
    keys = []   # (t, x, hard)
    for s in samples:
        t, faces = s["t"], s["faces"]
        hard = s["cut"] or cam is None
        target = None
        if faces:
            byid = {f[0]: f for f in faces}
            span_l = min(f[1] - f[2] * 0.8 for f in faces)
            span_r = max(f[1] + f[2] * 0.8 for f in faces)
            if len(faces) > 1 and span_r - span_l <= cw * 0.9:
                target = clamp((span_l + span_r) / 2 - cw / 2)   # everyone fits: frame the group
                subject = None
            else:
                def score(f):
                    return f[4] * 4.0 + (f[2] / sw) * 1.5 + 0.15 * (1 - abs(f[1] - sw / 2) / (sw / 2))
                best = max(faces, key=score)
                if subject not in byid or s["cut"]:
                    if subject is not None and subject not in byid and t - last_switch < 0.8 and not s["cut"]:
                        pass  # brief detection dropout: hold
                    else:
                        if subject is not None:
                            hard = True
                        subject, last_switch, challenger = best[0], t, None
                elif best[0] != subject and score(best) > score(byid[subject]) * 1.35 + 0.03:
                    if challenger != best[0]:
                        challenger, challenger_since = best[0], t
                    elif t - challenger_since >= 0.6 and t - last_switch >= 1.5:
                        subject, last_switch, challenger, hard = best[0], t, None, True
                else:
                    challenger = None
                if subject in byid:
                    target = clamp(byid[subject][1] - cw / 2)
        if target is None:
            target = cam if cam is not None else max_x / 2
        if hard or cam is None:
            cam = target
        else:
            err = target - cam
            if abs(err) > cw * 0.07:          # dead zone, then ease in
                cam += err * 0.3
        keys.append((t, cam, hard))
    return {"mode": "track", "keys": keys, "cw": cw}


# ---------------- rendering ----------------

def _write_cmds(keys, path, fps=30.0):
    lines = []
    if not keys:
        return
    end_t = keys[-1][0] + 1.0
    k = 0
    t = 0.0
    while t <= end_t:
        while k + 1 < len(keys) and keys[k + 1][0] <= t:
            k += 1
        x0 = keys[k][1]
        if k + 1 < len(keys) and not keys[k + 1][2]:
            t0, t1, x1 = keys[k][0], keys[k + 1][0], keys[k + 1][1]
            a = (t - t0) / (t1 - t0) if t1 > t0 else 0
            x = x0 + (x1 - x0) * max(0.0, min(1.0, a))
        else:
            x = x0
        lines.append(f"{t:.4f} crop@cam x {int(x) // 2 * 2};")
        t += 1.0 / fps
    Path(path).write_text("\n".join(lines) + "\n")


def plan_filter(plan, sw, sh, workdir, out_w=W, out_h=H):
    """ffmpeg filter chain (string, no input/output labels) producing out_w x out_h."""
    from .media import filter_path
    mode = plan.get("mode")
    if mode == "vertical" or sw / sh <= out_w / out_h + 0.01:
        return f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},setsar=1"
    if mode == "zoom":  # gameplay: keep the middle ~60% of the frame big, blurred fill behind
        zw = int(sw * 0.62) // 2 * 2
        return (f"split=2[bg][fg];[bg]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},"
                f"boxblur=24:2,eq=brightness=-0.1[bgb];[fg]crop={zw}:{sh}:{(sw - zw) // 2}:0,scale={out_w}:-2:flags=lanczos[fgs];"
                f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1")
    if mode == "facecam":
        return _facecam_filter(plan, sw, sh, out_w, out_h)
    if mode == "fit":
        return (f"split=2[bg][fg];[bg]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},"
                f"boxblur=24:2,eq=brightness=-0.08[bgb];[fg]scale={out_w}:-2[fgs];[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1")
    cw = crop_width(sw, sh)
    if mode == "track" and plan.get("keys"):
        cmds = Path(workdir) / f"cam_{id(plan)}.txt"
        _write_cmds(plan["keys"], cmds)
        x0 = int(plan["keys"][0][1]) // 2 * 2
        track = (f"sendcmd=f='{filter_path(cmds)}',crop@cam={cw}:{sh}:{x0}:0,"
                 f"scale={out_w}:{out_h}:flags=lanczos,setsar=1")
    else:
        track = f"crop={cw}:{sh}:{(sw - cw) // 2}:0,scale={out_w}:{out_h}:flags=lanczos,setsar=1"
    split = plan.get("split")
    if not split:
        return track
    bw, bh = split["size"]
    segs = split["segments"]
    lines = [f"{t0:.3f} crop@top x {xa}, crop@top y {ya}, crop@bot x {xb}, crop@bot y {yb};"
             for t0, t1, ((xa, ya), (xb, yb)) in segs]
    scmds = Path(workdir) / f"split_{id(plan)}.txt"
    scmds.write_text("\n".join(lines) + "\n")
    (xa, ya), (xb, yb) = segs[0][2]
    hh = out_h // 2
    enable = "+".join(f"between(t,{t0:.3f},{t1:.3f})" for t0, t1, _ in segs)
    return (f"split=2[rf_t][rf_s];[rf_t]{track}[rf_trk];"
            f"[rf_s]sendcmd=f='{filter_path(scmds)}',split=2[rf_a][rf_b];"
            f"[rf_a]crop@top={bw}:{bh}:{xa}:{ya},scale={out_w}:{hh}:flags=lanczos,setsar=1[rf_top];"
            f"[rf_b]crop@bot={bw}:{bh}:{xb}:{yb},scale={out_w}:{hh}:flags=lanczos,setsar=1[rf_bot];"
            f"[rf_top][rf_bot]vstack[rf_spl];"
            f"[rf_trk][rf_spl]overlay=0:0:enable='{enable}',setsar=1")


# Backwards-compatible helpers
def vertical_filter(mode, src_w, src_h, keys=None, out_w=W, out_h=H):
    return plan_filter({"mode": "center" if mode == "face" else mode}, src_w, src_h, ".", out_w, out_h)


def cover_filter(src_w, src_h, out_w=W, out_h=H):
    return f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},setsar=1"


# ---------------- gaming: facecam ----------------

FACECAM_SIZES = {"small": 0.25, "medium": 1 / 3, "large": 0.4}
CORNERS = ("top-left", "top-right", "bottom-left", "bottom-right")


def detect_facecam(path, duration, sw, sh, samples=30):
    """Find a streamer facecam: a small face that stays in the same spot across the video, then snap the
    box to the overlay's real borders (persistent edges where the busy gameplay meets the calmer webcam).
    Returns {"rect": [x, y, w, h], "corner": str} in source pixels, or None."""
    aw = ANALYSIS_W
    ah = int(round(sh * aw / sw / 2)) * 2
    det = Detector(aw, ah)
    hits, grays = [], []
    for t in np.linspace(duration * 0.03, duration * 0.97, samples):
        out = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1",
                              "-vf", f"scale={aw}:{ah}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True)
        if len(out.stdout) < aw * ah * 3:
            continue
        frame = np.frombuffer(out.stdout[: aw * ah * 3], np.uint8).reshape(ah, aw, 3)
        grays.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        for f in det(frame):
            if f["w"] < aw * 0.22:  # facecam faces are small relative to the game
                hits.append((f["cx"], f["cy"], f["w"], f["h"]))
    if not hits:
        return None
    best = []  # densest cluster of face positions
    for cx, cy, _, _ in hits:
        grp = [h for h in hits if abs(h[0] - cx) < aw * 0.06 and abs(h[1] - cy) < ah * 0.08]
        if len(grp) > len(best):
            best = grp
    if len(best) < max(3, len(grays) * 0.3):
        return None
    face = [float(np.median([h[i] for h in best])) for i in range(4)]
    x0, y0, x1, y1 = _snap_cam_box(grays, face, aw, ah)
    # step a hair inside the borders so no sliver of gameplay / overlay frame survives
    ix, iy = 1.5 + (x1 - x0) * 0.01, 1.5 + (y1 - y0) * 0.01
    x0, y0, x1, y1 = x0 + ix, y0 + iy, x1 - ix, y1 - iy
    k = sw / aw
    x, y, w, h = x0 * k, y0 * k, (x1 - x0) * k, (y1 - y0) * k
    x, y = max(0, x), max(0, y)
    w, h = min(w, sw - x), min(h, sh - y)
    cx, cy = face[0] * k, face[1] * k
    corner = ("top" if cy < sh / 2 else "bottom") + "-" + ("left" if cx < sw / 2 else "right")
    return {"rect": [int(x) // 2 * 2, int(y) // 2 * 2, int(w) // 2 * 2, int(h) // 2 * 2], "corner": corner}


def _snap_cam_box(grays, face, aw, ah):
    """Webcam box around a face (analysis coords). Each side is the column/row with the strongest mix of a
    persistent edge and a jump in temporal variance (game outside moves more than the room inside)."""
    cx, cy, fw, fh = face
    G = np.stack(grays).astype(np.float32)
    std = G.std(0)
    gx = np.median(np.stack([np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)) for g in grays]), 0)
    gy = np.median(np.stack([np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)) for g in grays]), 0)
    gnorm = float(np.percentile(np.maximum(gx, gy), 99.5)) + 1e-3
    snorm = float(np.percentile(std, 95)) + 1e-3
    K = 5
    # fallback guess (the old fixed-ratio box)
    guess = [cx - fw * 1.5, cy - fh * 1.2, cx + fw * 1.5, cy + fh * 1.4]

    def side(axis, lo, hi, band, inside_sign, edge_at):
        """axis 0: vertical lines (columns), 1: horizontal lines (rows). inside_sign=+1 if the cam lies at
        larger coordinates than the line. Returns best line position or None."""
        b0, b1 = int(max(0, band[0])), int(min((ah if axis == 0 else aw), band[1]))
        lim = aw if axis == 0 else ah
        lo, hi = int(max(0, lo)), int(min(lim - 1, hi))
        if b1 - b0 < 4 or hi <= lo:
            return None
        best, best_s = None, 0.0
        for c in range(lo, hi + 1):
            if axis == 0:
                e = gx[b0:b1, c].mean() / gnorm
                left = std[b0:b1, max(0, c - K):c]; right = std[b0:b1, c + 1:c + 1 + K]
            else:
                e = gy[c, b0:b1].mean() / gnorm
                left = std[max(0, c - K):c, b0:b1]; right = std[c + 1:c + 1 + K, b0:b1]
            if left.size == 0 or right.size == 0:
                continue
            outside, inside = (left, right) if inside_sign > 0 else (right, left)
            step = (outside.mean() - inside.mean()) / snorm
            s = e + 1.5 * step
            if step > 0.08 and e > 0.08 and s > best_s:
                best, best_s = c, s
        if best is None and edge_at is not None:
            return edge_at  # nothing strong: the cam probably touches the frame edge
        return best

    x0, y0, x1, y1 = guess
    for _ in range(2):  # second pass uses the first pass's extent as the band
        rows = (cy - fh * 1.0, cy + fh * 1.0) if _ == 0 else (y0 + (y1 - y0) * 0.1, y1 - (y1 - y0) * 0.1)
        cols = (cx - fw * 1.0, cx + fw * 1.0) if _ == 0 else (x0 + (x1 - x0) * 0.1, x1 - (x1 - x0) * 0.1)
        L = side(0, cx - fw * 4, cx - fw * 0.55, rows, +1, 0 if cx - fw * 4 <= 2 else None)
        R = side(0, cx + fw * 0.55, cx + fw * 4, rows, -1, aw if cx + fw * 4 >= aw - 3 else None)
        T = side(1, cy - fh * 3.2, cy - fh * 0.6, cols, +1, 0 if cy - fh * 3.2 <= 2 else None)
        B = side(1, cy + fh * 0.5, cy + fh * 4.5, cols, -1, ah if cy + fh * 4.5 >= ah - 3 else None)
        x0 = L if L is not None else guess[0]
        x1 = R if R is not None else guess[2]
        y0 = T if T is not None else guess[1]
        y1 = B if B is not None else guess[3]
        # lines within a few px of the frame edge are the edge
        x0 = 0 if x0 < 3 else x0; y0 = 0 if y0 < 3 else y0
        x1 = aw if x1 > aw - 4 else x1; y1 = ah if y1 > ah - 4 else y1
    return max(0, x0), max(0, y0), min(aw, x1 + 1 if x1 < aw else aw), min(ah, y1 + 1 if y1 < ah else ah)


def corner_rect(corner, sw, sh, frac=0.27):
    w, h = int(sw * frac) // 2 * 2, int(sh * frac) // 2 * 2
    x = 0 if corner.endswith("left") else sw - w
    y = 0 if corner.startswith("top") else sh - h
    return [x, y, w, h]


def facecam_height(plan, out_h=H):
    """Height in px of the facecam band. size: 'small'|'medium'|'large' or a percentage (15-60)."""
    size = plan.get("size", "medium")
    try:
        frac = float(size) / 100.0
    except (TypeError, ValueError):
        frac = FACECAM_SIZES.get(size, 1 / 3)
    return int(out_h * min(0.6, max(0.15, frac))) // 2 * 2


def game_area(plan, out_h=H):
    """(y0, y1) of the gameplay band in the output, for placing captions."""
    cam_h = facecam_height(plan, out_h)
    return (0, out_h - cam_h) if plan.get("cam_pos") == "bottom" else (cam_h, out_h)


def _facecam_filter(plan, sw, sh, out_w, out_h):
    rect = plan.get("rect")
    if not rect:  # no facecam: plain zoomed gameplay
        return plan_filter({"mode": "zoom"}, sw, sh, ".", out_w, out_h)
    x, y, w, h = [int(v) // 2 * 2 for v in rect]
    x, y = max(0, min(x, sw - 16)), max(0, min(y, sh - 16))
    w, h = max(16, min(w, sw - x)), max(16, min(h, sh - y))
    cam_h = facecam_height(plan, out_h)
    game_h = out_h - cam_h
    crop = f"crop={w}:{h}:{x}:{y}"
    if plan.get("cam_fit", "blur") == "fill":  # crop the cam to fill its band
        cam = f"{crop},scale={out_w}:{cam_h}:force_original_aspect_ratio=increase,crop={out_w}:{cam_h},setsar=1"
    else:  # whole cam, centred over a blurred copy of itself (no giant face, no gameplay edges)
        cam = (f"{crop},split=2[fcb][fcf];[fcb]scale={out_w}:{cam_h}:force_original_aspect_ratio=increase,"
               f"crop={out_w}:{cam_h},boxblur=24:3,eq=brightness=-0.06[fcbb];"
               f"[fcf]scale={out_w}:{cam_h}:force_original_aspect_ratio=decrease:flags=lanczos,setsar=1[fcfs];"
               f"[fcbb][fcfs]overlay=(W-w)/2:(H-h)/2,setsar=1")
    # blur the webcam out of the gameplay so the streamer isn't shown twice
    hide = f"split=2[fgs][fgc];[fgc]{crop},boxblur=30:3[fgb];[fgs][fgb]overlay={x}:{y}"
    if plan.get("gameplay_fit") == "fit":
        game = (f"{hide},split=2[gb][gf];[gb]scale={out_w}:{game_h}:force_original_aspect_ratio=increase,"
                f"crop={out_w}:{game_h},boxblur=20:2[gbb];[gf]scale={out_w}:-2[gfs];"
                f"[gbb][gfs]overlay=(W-w)/2:(H-h)/2,setsar=1")
    else:  # crop the gameplay to fill its band (keeps the centre of the action big)
        gw = min(sw, int(sh * out_w / game_h)) // 2 * 2
        gx0 = (sw - gw) // 2
        visible = x < gx0 + gw and x + w > gx0
        game = (f"{hide}," if visible else "") + f"crop={gw}:{sh}:{gx0}:0,scale={out_w}:{game_h}:flags=lanczos,setsar=1"
    order = "[fc_game][fc_cam]" if plan.get("cam_pos") == "bottom" else "[fc_cam][fc_game]"
    return f"split=2[fc_a][fc_b];[fc_a]{cam}[fc_cam];[fc_b]{game}[fc_game];{order}vstack,setsar=1"

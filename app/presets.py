"""Content types for AutoClip. Each type picks a detection engine and sensible defaults; the UI renders
its configuration form from this file."""

LAYOUTS = {
    "auto": "Auto (follow speaker + split wide shots)",
    "face": "Follow speaker",
    "split": "Split screen (two people)",
    "facecam": "Facecam + gameplay (stacked)",
    "zoom": "Zoomed gameplay + blur",
    "fit": "Full frame + blur",
    "center": "Center crop",
}

TYPES = {
    "podcast": {
        "label": "Podcast / Interview", "emoji": "🎙️",
        "desc": "Talking heads. Clips are chosen from what is said (transcript + AI).",
        "engine": "transcript",
        "layouts": ["auto", "face", "split", "center", "fit"],
        "defaults": {"count": 5, "min_len": 20, "max_len": 60, "transcribe": True, "use_ai": True, "vision": False,
                     "layout": "auto", "style": "bold", "position": "lower", "title_mode": "intro", "game": "",
                     "weights": {"action": 0, "motion": 0, "reactions": 0, "cuts": 0}},
    },
    "gaming_stream": {
        "label": "Gaming stream (facecam)", "emoji": "🎮",
        "desc": "Streamer playing with a facecam and commentary. Clips from in-game action and big reactions.",
        "engine": "signals",
        "layouts": ["facecam", "zoom", "fit", "center"],
        "defaults": {"count": 6, "min_len": 15, "max_len": 45, "transcribe": True, "use_ai": True, "vision": True,
                     "layout": "facecam", "facecam": "auto", "facecam_size": 33, "facecam_fit": "blur", "facecam_pos": "top", "gameplay_fit": "crop",
                     "style": "bold", "position": "middle", "title_mode": "intro", "game": "GTA 6",
                     "weights": {"action": 1.0, "motion": 0.6, "reactions": 1.3, "cuts": 0.2}},
    },
    "gameplay": {
        "label": "Gameplay (no commentary)", "emoji": "🚗",
        "desc": "Raw gameplay. Clips from gunfights, explosions, crashes and chases (game audio + motion + AI vision).",
        "engine": "signals",
        "layouts": ["zoom", "fit", "center"],
        "defaults": {"count": 6, "min_len": 12, "max_len": 40, "transcribe": False, "use_ai": True, "vision": True,
                     "layout": "zoom", "style": "none", "position": "lower", "title_mode": "always", "game": "GTA 6",
                     "weights": {"action": 1.2, "motion": 0.8, "reactions": 0, "cuts": 0.2}},
    },
    "trailer": {
        "label": "Trailer / Cinematic", "emoji": "🎬",
        "desc": "Trailers, cutscenes and edits. Clips built from the strongest shots, cut on scene changes.",
        "engine": "signals",
        "layouts": ["zoom", "fit", "center"],
        "defaults": {"count": 5, "min_len": 8, "max_len": 25, "transcribe": False, "use_ai": True, "vision": True,
                     "layout": "zoom", "style": "none", "position": "lower", "title_mode": "always", "game": "GTA 6",
                     "snap_cuts": True, "weights": {"action": 0.8, "motion": 0.5, "reactions": 0, "cuts": 1.0}},
    },
    "other": {
        "label": "Other / Mixed", "emoji": "✨",
        "desc": "Vlogs, IRL, sports, anything. Combines what is said with audio and motion.",
        "engine": "signals",
        "layouts": ["fit", "zoom", "auto", "center", "facecam"],
        "defaults": {"count": 5, "min_len": 15, "max_len": 60, "transcribe": True, "use_ai": True, "vision": False,
                     "layout": "fit", "facecam": "auto", "facecam_size": 33, "facecam_fit": "blur", "facecam_pos": "top", "gameplay_fit": "crop",
                     "style": "bold", "position": "lower", "title_mode": "intro", "game": "",
                     "weights": {"action": 0.8, "motion": 0.5, "reactions": 0.8, "cuts": 0.3}},
    },
}


def public():
    return {"types": TYPES, "layouts": LAYOUTS}


def resolve(content_type, config):
    t = TYPES.get(content_type) or TYPES["podcast"]
    cfg = {**t["defaults"], **(config or {})}
    cfg["weights"] = {**t["defaults"]["weights"], **((config or {}).get("weights") or {})}
    return t, cfg

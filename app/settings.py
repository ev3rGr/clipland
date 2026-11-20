"""User-configurable AI providers, stored locally in data/settings.json (keys never leave this machine
except to the provider you pick)."""
import copy
import json
import os
import threading

from .config import DATA

PATH = DATA / "settings.json"
_lock = threading.Lock()

DEFAULTS = {
    "llm": {
        # ollama | claude_cli | anthropic | openai_compat
        "provider": "ollama",
        "ollama_model": "",
        "claude_cli_model": "sonnet",          # alias (sonnet/opus/haiku) or full model id
        "anthropic_model": "claude-opus-5-5",
        "anthropic_effort": "high",
        "anthropic_api_key": "",
        "openai_base_url": "https://api.openai.com/v1",
        "openai_model": "",
        "openai_api_key": "",
    },
    "transcribe": {
        "provider": "local",                   # local | openai_compat
        "whisper_model": os.environ.get("CLIPLAND_WHISPER", "small"),
        "api_base_url": "https://api.groq.com/openai/v1",
        "api_model": "whisper-large-v3",
        "api_key": "",
    },
    "features": {
        "caption_cleanup": False,              # LLM fixes transcription mistakes in captions
    },
}
SECRET_FIELDS = {("llm", "anthropic_api_key"), ("llm", "openai_api_key"), ("transcribe", "api_key")}

_cache = None


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        elif k in out or not isinstance(base, dict):
            out[k] = v
    return out


def get():
    global _cache
    with _lock:
        if _cache is None:
            try:
                _cache = _merge(DEFAULTS, json.loads(PATH.read_text()))
            except (FileNotFoundError, json.JSONDecodeError):
                _cache = copy.deepcopy(DEFAULTS)
        return copy.deepcopy(_cache)


def update(patch: dict):
    """Merge a patch. Secret fields: empty string = keep, '__clear__' = remove."""
    global _cache
    cur = get()
    for section, vals in (patch or {}).items():
        if section not in DEFAULTS or not isinstance(vals, dict):
            continue
        for k, v in vals.items():
            if k not in DEFAULTS[section]:
                continue
            if (section, k) in SECRET_FIELDS:
                if v == "__clear__":
                    v = ""
                elif not v:
                    continue
            cur[section][k] = type(DEFAULTS[section][k])(v) if DEFAULTS[section][k] is not None else v
    with _lock:
        tmp = PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(cur, indent=2))
        os.chmod(tmp, 0o600)
        tmp.replace(PATH)
        _cache = cur
    return public()


def public():
    s = get()
    for section, k in SECRET_FIELDS:
        val = s[section][k]
        s[section][k] = ""
        s[section][k + "_set"] = bool(val)
        s[section][k + "_hint"] = ("…" + val[-4:]) if val else ""
    return s

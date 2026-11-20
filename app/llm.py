"""LLM layer with interchangeable providers. Everything calls `chat(prompt, schema=...)` and gets a dict back.

Providers (pick in Settings):
  ollama        - free local models (default)
  claude_cli    - your Claude Pro/Max subscription through the official Claude Code CLI (`claude -p`)
  anthropic     - Anthropic API key (official `anthropic` SDK)
  openai_compat - any OpenAI-compatible endpoint (OpenAI, Groq, OpenRouter, Gemini, LM Studio, ...)
"""
import base64
import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import httpx

from . import settings
from .config import OLLAMA_URL, WORK

PROVIDER_LABELS = {
    "ollama": "Local (Ollama)",
    "claude_cli": "Claude subscription",
    "anthropic": "Anthropic API",
    "openai_compat": "OpenAI-compatible API",
}


class LLMError(RuntimeError):
    pass


# ---------------- provider discovery ----------------

def ollama_models():
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=2)
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


def models():  # kept for /api/status
    return ollama_models()


def claude_cli_path():
    return shutil.which("claude") or next(
        (p for p in (os.path.expanduser("~/.local/bin/claude"), os.path.expanduser("~/.claude/local/claude")) if os.path.exists(p)), None)


def _ollama_model(cfg):
    ms = ollama_models()
    want = cfg.get("ollama_model") or os.environ.get("CLIPLAND_LLM", "")
    if want and want in ms:
        return want
    return ms[0] if ms else None


def current():
    """(provider, model label) or (provider, None) when not usable."""
    cfg = settings.get()["llm"]
    p = cfg["provider"]
    if p == "ollama":
        return p, _ollama_model(cfg)
    if p == "claude_cli":
        return p, (cfg["claude_cli_model"] or "sonnet") if claude_cli_path() else None
    if p == "anthropic":
        ok = cfg["anthropic_api_key"] or os.environ.get("ANTHROPIC_API_KEY")
        return p, cfg["anthropic_model"] if ok else None
    if p == "openai_compat":
        return p, cfg["openai_model"] if (cfg["openai_model"] and cfg["openai_base_url"]) else None
    return p, None


def pick_model():
    return current()[1]


def available():
    return current()[1] is not None


VISION_HINTS = ("llava", "vision", "vl", "gemma3", "minicpm-v", "moondream", "llama4", "bakllava", "granite3.2-vision", "mistral-small3")


def supports_vision():
    p, m = current()
    if not m:
        return False
    if p == "ollama":
        return any(h in m.lower() for h in VISION_HINTS)
    return True


def big_context():
    """Cloud models can read a whole long transcript at once; small local models need chunks."""
    return settings.get()["llm"]["provider"] != "ollama"


# ---------------- core call ----------------

def chat(prompt, system=None, schema=None, temperature=0.7, timeout=600, images=None):
    """Return parsed JSON (dict). `schema` is a JSON Schema for the expected object.
    `images`: optional list of local JPEG/PNG paths the model should look at (in order)."""
    cfg = settings.get()["llm"]
    p = cfg["provider"]
    system = system or "You are a precise assistant that replies only with JSON."
    images = [Path(i) for i in (images or [])]
    if p == "ollama":
        return _ollama(cfg, prompt, system, schema, temperature, timeout, images)
    if p == "claude_cli":
        return _claude_cli(cfg, prompt, system, schema, timeout, images)
    if p == "anthropic":
        return _anthropic(cfg, prompt, system, schema, images)
    if p == "openai_compat":
        return _openai(cfg, prompt, system, schema, temperature, timeout, images)
    raise LLMError(f"Unknown provider {p}")


def _parse_json(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise LLMError(f"Model did not return JSON: {text[:200]}")


def _schema_hint(schema):
    return f"\n\nReply with only a JSON object matching this JSON Schema:\n{json.dumps(schema)}" if schema else "\n\nReply with only JSON."


def _b64(path):
    return base64.b64encode(Path(path).read_bytes()).decode()


def _mime(path):
    return "image/png" if str(path).lower().endswith(".png") else "image/jpeg"


def _ollama(cfg, prompt, system, schema, temperature, timeout, images=()):
    model = _ollama_model(cfg)
    if not model:
        raise LLMError("No local model installed. Run: ollama pull qwen2.5:3b — or pick another provider in Settings.")
    body = {"model": model, "stream": False, "format": schema or "json",
            "options": {"temperature": temperature, "num_ctx": 8192},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt + _schema_hint(schema)}]}
    if images:
        body["messages"][1]["images"] = [_b64(i) for i in images]
    r = httpx.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=timeout)
    r.raise_for_status()
    return _parse_json(r.json()["message"]["content"])


def _claude_cli(cfg, prompt, system, schema, timeout, images=()):
    """Uses the Claude Code CLI in headless mode, authenticated with the user's own subscription login.
    Tools, MCP servers and project settings are disabled so it acts as a plain text model."""
    exe = claude_cli_path()
    if not exe:
        raise LLMError("Claude Code CLI not found. Install it (npm i -g @anthropic-ai/claude-code) and run `claude` once to log in.")
    cwd = WORK / "claude_cli"
    cwd.mkdir(exist_ok=True)
    if images:
        # Claude Code views images with its Read tool: copy them into a private folder and allow only Read.
        cwd = cwd / uuid.uuid4().hex[:8]
        cwd.mkdir()
        names = []
        for k, img in enumerate(images):
            name = f"image_{k:02d}{Path(img).suffix or '.jpg'}"
            shutil.copy(img, cwd / name)
            names.append(name)
        prompt = ("First use the Read tool to look at each of these image files in the current directory, in order: "
                  + ", ".join(names) + ". Image N corresponds to item N below.\n\n" + prompt)
    tools = ["--tools", "Read", "--allowedTools", "Read"] if images else ["--tools", ""]
    cmd = [exe, "-p", "--output-format", "json", "--model", cfg["claude_cli_model"] or "sonnet",
           *tools, "--no-session-persistence", "--strict-mcp-config", "--setting-sources", "",
           "--system-prompt", system]
    if schema:
        cmd += ["--json-schema", json.dumps(schema)]
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDECODE") and k != "CLAUDE_CODE_ENTRYPOINT"}
    env.pop("ANTHROPIC_API_KEY", None)  # make sure the subscription login is used, not an API key
    try:
        out = subprocess.run(cmd, input=prompt if schema else prompt + _schema_hint(None), capture_output=True,
                             text=True, timeout=timeout, cwd=cwd, env=env)
    except subprocess.TimeoutExpired:
        raise LLMError("Claude CLI timed out")
    finally:
        if images:
            shutil.rmtree(cwd, ignore_errors=True)
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        msg = (out.stderr or out.stdout or "").strip()[-400:]
        raise LLMError(f"Claude CLI failed: {msg or 'no output'}. Run `claude` in a terminal to check you're logged in.")
    if data.get("is_error"):
        raise LLMError(f"Claude CLI error: {data.get('result') or data.get('subtype')}")
    if schema and isinstance(data.get("structured_output"), dict):
        return data["structured_output"]
    return _parse_json(data.get("result", ""))


def _anthropic(cfg, prompt, system, schema, images=()):
    import anthropic
    client = anthropic.Anthropic(api_key=cfg["anthropic_api_key"] or None, max_retries=3)
    kwargs = dict(model=cfg["anthropic_model"] or "claude-opus-5-5", max_tokens=32000, system=system,
                  messages=[{"role": "user", "content": prompt}],
                  output_config={"effort": cfg.get("anthropic_effort") or "high"})
    if schema:
        kwargs["output_config"]["format"] = {"type": "json_schema", "schema": schema}
    else:
        kwargs["messages"][0]["content"] += _schema_hint(None)
    if images:
        blocks = []
        for k, img in enumerate(images):
            blocks.append({"type": "text", "text": f"Image {k}:"})
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": _mime(img), "data": _b64(img)}})
        kwargs["messages"][0]["content"] = blocks + [{"type": "text", "text": kwargs["messages"][0]["content"]}]
    try:
        # Streaming avoids HTTP timeouts on long transcripts. If a request is declined,
        # server-side fallbacks retry it on Anthropic's recommended fallback model.
        with client.beta.messages.stream(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs) as stream:
            msg = stream.get_final_message()
    except anthropic.AuthenticationError:
        raise LLMError("Anthropic API key was rejected. Check it in Settings.")
    except anthropic.NotFoundError:
        raise LLMError(f"Unknown Anthropic model: {kwargs['model']}")
    except anthropic.RateLimitError:
        raise LLMError("Anthropic rate limit reached — wait a minute and retry.")
    except anthropic.BadRequestError as e:
        raise LLMError(f"Anthropic rejected the request: {e.message}")
    except anthropic.APIStatusError as e:
        raise LLMError(f"Anthropic API error {e.status_code}: {e.message}")
    except anthropic.APIConnectionError:
        raise LLMError("Can't reach the Anthropic API — check your internet connection.")
    if msg.stop_reason == "refusal":
        raise LLMError("Claude declined this request.")
    if msg.stop_reason == "max_tokens":
        raise LLMError("Claude's answer was cut off (max_tokens). Try fewer clips.")
    text = next((b.text for b in msg.content if b.type == "text"), "")
    return _parse_json(text)


def _openai(cfg, prompt, system, schema, temperature, timeout, images=()):
    base = cfg["openai_base_url"].rstrip("/")
    headers = {"Authorization": f"Bearer {cfg['openai_api_key']}"} if cfg["openai_api_key"] else {}
    body = {"model": cfg["openai_model"], "temperature": temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt + _schema_hint(schema)}],
            "response_format": {"type": "json_object"}}
    if images:
        parts = []
        for k, img in enumerate(images):
            parts.append({"type": "text", "text": f"Image {k}:"})
            parts.append({"type": "image_url", "image_url": {"url": f"data:{_mime(img)};base64,{_b64(img)}"}})
        body["messages"][1]["content"] = parts + [{"type": "text", "text": body["messages"][1]["content"]}]
    r = httpx.post(f"{base}/chat/completions", json=body, headers=headers, timeout=timeout)
    if r.status_code == 400 and "response_format" in r.text:  # some servers don't support json mode
        body.pop("response_format")
        r = httpx.post(f"{base}/chat/completions", json=body, headers=headers, timeout=timeout)
    if r.status_code >= 400:
        raise LLMError(f"API error {r.status_code}: {r.text[:300]}")
    return _parse_json(r.json()["choices"][0]["message"]["content"])


def test():
    p, m = current()
    if not m:
        raise LLMError(f"{PROVIDER_LABELS.get(p, p)} isn't configured yet.")
    out = chat("Reply with {\"ok\": true, \"model\": \"<your model name>\"}.",
               schema={"type": "object", "properties": {"ok": {"type": "boolean"}, "model": {"type": "string"}},
                       "required": ["ok", "model"], "additionalProperties": False}, timeout=120)
    return {"provider": PROVIDER_LABELS.get(p, p), "model": m, "reply": out}


# ---------------- tasks ----------------

def _obj(props, required=None):
    return {"type": "object", "properties": props, "required": required or list(props), "additionalProperties": False}


S = {"type": "string"}
I = {"type": "integer"}

REDDIT_SCHEMA = _obj({"subreddit": S, "title": S, "body": S})
FAKETEXT_SCHEMA = _obj({"contact": S, "messages": {"type": "array", "items": _obj({"from": {"type": "string", "enum": ["me", "them"]}, "text": S})}})
SCRIPT_SCHEMA = _obj({"script": S})
CLIPS_SCHEMA = _obj({"clips": {"type": "array", "items": _obj({
    "start_index": I, "end_index": I, "title": S, "score": I, "reason": S, "description": S,
    "hashtags": {"type": "array", "items": S}})}})
FIXES_SCHEMA = _obj({"fixes": {"type": "array", "items": _obj({"i": I, "word": S})}})


def reddit_story(prompt):
    sys = ("You write viral first-person Reddit stories (AITA, TIFU, relationships, revenge) for short videos. "
           "Hook in the first sentence, conversational, a twist near the end. 180-260 words. No hashtags, no emojis.")
    data = chat(f"Topic/idea: {prompt or 'surprise me'}", system=sys, schema=REDDIT_SCHEMA, temperature=0.9)
    return {"subreddit": data.get("subreddit", "r/AskReddit"), "title": data.get("title", ""), "body": data.get("body", "")}


def fake_text(prompt):
    sys = ("You write funny, dramatic text message conversations for short videos. 10-16 short messages, "
           "natural texting style, a punchline at the end. 'me' is the phone owner, 'them' is the contact. "
           "'contact' is the contact's display name (e.g. 'Mom', 'Landlord', 'Jake'). No emojis.")
    data = chat(f"Idea: {prompt or 'surprise me'}", system=sys, schema=FAKETEXT_SCHEMA, temperature=0.9)
    msgs = [{"from": "me" if m.get("from") == "me" else "them", "text": str(m.get("text", "")).strip()}
            for m in data.get("messages", []) if str(m.get("text", "")).strip()]
    contact = str(data.get("contact") or "").strip()
    if contact.lower() in ("", "them", "me", "name", "contact", "unknown"):
        contact = "Bestie"
    return {"contact": contact[:24], "messages": msgs}


def video_script(prompt):
    sys = "You write punchy voiceover scripts for 30-60 second vertical videos. Strong hook, no stage directions, no emojis."
    data = chat(f"Topic: {prompt}", system=sys, schema=SCRIPT_SCHEMA)
    return {"script": data.get("script", "")}


def pick_clips(listing, n, min_len, max_len):
    sys = ("You are a senior short-form video editor who has cut thousands of viral TikToks, Reels and Shorts "
           "from podcasts and long videos. You judge hooks, payoff, emotion, controversy, and whether a clip makes "
           "sense without context.")
    prompt = (
        f"Transcript sentences, each with [index] and (start-end seconds):\n{listing}\n\n"
        f"Pick up to {n} self-contained moments that would perform best as {min_len:.0f}-{max_len:.0f} second vertical clips.\n"
        "Rules: start on a sentence that hooks a cold viewer in the first 2 seconds (no 'and', 'so', or references to "
        "earlier context); end on a payoff or complete thought; clips must not overlap; respect the length range "
        "using the timestamps. Rank by viral potential.\n"
        "For each clip return start_index/end_index (inclusive sentence indices), a punchy 3-8 word on-screen hook "
        "title, score 0-100, a one-sentence reason, a 1-2 sentence post description, and 3-6 hashtags (with #)."
    )
    return chat(prompt, system=sys, schema=CLIPS_SCHEMA, temperature=0.3).get("clips", [])


def fix_caption_words(words):
    """Correct obvious transcription mistakes in-place. Each word keeps its timing; a word may be emptied
    to merge it into the previous one (e.g. '$10' ',000' -> '$10,000' '')."""
    if not words:
        return words
    for start in range(0, len(words), 350):
        chunk = words[start:start + 350]
        listing = " ".join(f"{i}:{w['word']}" for i, w in enumerate(chunk))
        prompt = (
            "These are speech-to-text caption words as index:word. Fix only clear transcription errors: misheard "
            "words, wrong names/brands, broken numbers (e.g. '$10' ',000' -> set first to '$10,000' and second to ''), "
            "missing apostrophes, and sentence punctuation/capitalisation. Never rephrase or translate. "
            "Return only the words you change.\n\n" + listing
        )
        try:
            fixes = chat(prompt, schema=FIXES_SCHEMA, temperature=0).get("fixes", [])
        except Exception as e:
            print("caption cleanup failed:", e)
            continue
        for f in fixes:
            i = f.get("i")
            if isinstance(i, int) and 0 <= i < len(chunk):
                chunk[i]["word"] = str(f.get("word", "")).strip()
    # merge emptied words into their predecessor's timing
    out = []
    for w in words:
        if not w["word"]:
            if out:
                out[-1]["end"] = max(out[-1]["end"], w["end"])
            continue
        out.append(w)
    return out


HIGHLIGHTS_SCHEMA = _obj({"clips": {"type": "array", "items": _obj({
    "index": I, "keep": {"type": "boolean"}, "score": I, "title": S, "reason": S, "description": S,
    "hashtags": {"type": "array", "items": S}})}})

TYPE_BRIEF = {
    "gaming_stream": "a gaming livestream with a facecam (judge both the in-game action and the streamer's reaction)",
    "gameplay": "raw gameplay footage without commentary",
    "trailer": "a trailer / cinematic video",
    "other": "a video",
}


def rank_highlights(items, n, content_type, game="", images=None):
    """items: [{index, start, end, reason, transcript}] + optional contact sheet per item (same order)."""
    subject = f" of {game}" if game else ""
    sys = ("You are a top short-form editor who runs a viral gaming clip channel. You know exactly what makes "
           "people stop scrolling: chaos, insane plays, funny fails, wild physics, big reactions, beautiful shots.")
    lines = []
    for it in items:
        line = f"[{it['index']}] {it['start']:.0f}s-{it['end']:.0f}s ({it['end'] - it['start']:.0f}s) detected: {it['reason']}"
        if it.get("transcript"):
            line += f' | said: "{it["transcript"][:300]}"'
        lines.append(line)
    look = ("Each image is a contact sheet of frames sampled across that candidate, left-to-right then top-to-bottom, "
            "with timestamps. ") if images else ""
    prompt = (
        f"These are candidate highlight clips from {TYPE_BRIEF.get(content_type, 'a video')}{subject}. {look}"
        f"Pick the best {n} for TikTok/Shorts. Set keep=false for boring, repetitive, menu/loading screens or unclear ones.\n\n"
        + "\n".join(lines) +
        f"\n\nFor every candidate return: index, keep, score 0-100 (viral potential), a punchy 2-7 word on-screen hook "
        f"title (no hashtags; reference what actually happens{', and the game name when natural' if game else ''}), "
        "a one-sentence reason, a 1-2 sentence post description, and 3-6 hashtags (with #)."
    )
    return chat(prompt, system=sys, schema=HIGHLIGHTS_SCHEMA, temperature=0.4, images=images, timeout=900).get("clips", [])

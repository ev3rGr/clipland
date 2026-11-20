# Clipland

A local, free, open-source short-form video studio. It does the same kind of work as the paid AI clipping
sites, but everything runs on your own machine. There are no credits, no watermark and no account.

```bash
./run.sh            # then open http://localhost:8000
```

## Features

| Page | What it does | Powered by |
|---|---|---|
| **AutoClip** | Long video → transcript → AI-scored viral moments → 9:16 clips that follow the speaker's face, with animated captions and a hook title. You can review and edit moments, preview them, add manual cuts, or render in one click. | faster-whisper (GPU), Ollama LLM + heuristic scorer, OpenCV, ffmpeg/NVENC |
| **Story Videos** | Reddit-style story → narrated voiceover, a post card during the title, word-by-word captions, gameplay background, optional music. The AI can write the story for you. | edge-tts neural voices, PIL, libass |
| **Fake Texts** | Scripted text conversation with a separate voice per person; bubbles pop in over the background. The AI can write the conversation. | edge-tts, PIL |
| **AI Voiceover** | Narrate a script over your video, a background, or export MP3 only. | edge-tts |
| **Auto Captions** | Burn 5 animated caption styles into any video, keep its size or convert it to 9:16, and export an `.srt`. | faster-whisper |
| **Free Tools** | Trim, compress (to a target MB), GIF, speed, reverse, mute, MP3, MP4, merge, aspect ratio, volume boost, speech enhancer, loudness balance, frame grab | ffmpeg |
| **Library** | Uploads, background gameplay, music, exports. Select files to download or delete. Several files download as one `.zip`. | |
| **Calculators** | Views→money, CPM/RPM, posts to 1M views, clips per video, campaign payouts | |

## Add videos from a link
Every video picker has a link box. Paste or drag in a link and Clipland detects the site: YouTube (videos and Shorts),
Twitch (VODs and clips), Kick, TikTok, X, Instagram, Facebook, Reddit, Vimeo, Streamable, Medal, Google Drive, Dropbox,
direct `.mp4` links, and anything else [yt-dlp](https://github.com/yt-dlp/yt-dlp) supports. It shows the title, length
and best available quality, then downloads the video and selects it.
- **Batch:** paste several links at once (one per line), or a playlist or channel page (YouTube `@channel/videos`,
  playlists, Twitch `/videos` and `/clips`, Kick, TikTok `@user`). You get a list to tick: **Download selected** or
  **Download all**. Two downloads run at a time, each with its own progress.
- **Long videos:** anything over 2 hours waits for you to choose a part, for example 1:20:00 → 1:50:00 of a stream, so
  you don't pull a 10-hour VOD.
- **Quality:** you can cap the quality (4K → 480p). H.264 is preferred because it decodes and edits fastest.
- **No duplicates:** a link you've already downloaded is reused instead of downloaded again.
- **Own lane:** downloads run alongside renders instead of waiting behind them.

If a site stops working, update the downloader with `.venv/bin/python -m pip install -U yt-dlp` (or `uv pip install -U yt-dlp`).

## AutoClip content types
Before clipping, pick the type of video. Each type has its own engine and settings, and your last settings are remembered per type:

| Type | How highlights are found | Default layout |
|---|---|---|
| 🎙️ Podcast / Interview | Transcript + AI pick what is said | Follow speaker, split wide shots |
| 🎮 Gaming stream (facecam) | Game audio + motion + streamer reactions, then AI watches the candidates | Facecam (top or bottom) + gameplay |
| 🚗 Gameplay (no commentary) | Gunfire, explosions and crashes (audio onsets and loudness), motion, flashes, then AI vision | Zoomed gameplay + blur |
| 🎬 Trailer / Cinematic | Scene cuts + audio + motion; clips snap to cuts | Zoomed gameplay + blur |
| ✨ Other / Mixed | Speech + audio + motion combined | Full frame + blur |

Signal detection runs locally and quickly (about 1–3 min per hour of 1080p). With **AI vision** on, a contact sheet of frames
from each candidate goes to the selected AI. It drops boring parts like menus and loading screens, ranks the rest, and writes
titles, descriptions and hashtags. Sliders control what counts as a highlight.

**Facecam layout (streams):** the webcam is found automatically. Clipland looks for a face that stays in one spot, then
snaps the box to the overlay's real borders, where moving gameplay meets the calmer webcam. You can also draw or adjust
the box on any frame with **Adjust / draw facecam**. Options:
- Put the cam on top or at the bottom.
- **Whole cam + blur** shows the full webcam over a blurred copy of itself, with no giant face. **Fill** crops it to fill its band.
- Set the cam's height (15–60%) and choose to crop the gameplay or fit the whole frame.

The webcam is blurred out of the gameplay part, the hook title sits on the seam, and captions stay in the gameplay.
**Preview layout** renders one 9:16 frame so you can check before rendering.

## AI providers (AI Settings page)
Pick what does the thinking: picking moments, hook titles, descriptions and hashtags, script writing, and caption cleanup.

| Provider | Cost | Notes |
|---|---|---|
| **Local (Ollama)** | free | Offline and private. Small models pick weaker moments. |
| **Claude subscription** | your Pro/Max plan | Runs through the official Claude Code CLI (`claude -p`) on this machine, using your login. It reads the whole transcript in one pass. Each step is one message that counts toward your plan's limits. |
| **Anthropic API** | pay per token | Official `anthropic` SDK, Claude Opus 5.5 by default. |
| **OpenAI-compatible** | varies | OpenAI, Groq, OpenRouter, Gemini, LM Studio… |

For speech-to-text, use local faster-whisper (tiny → large-v3) or a cloud Whisper API (Groq `whisper-large-v3` has a free tier).
**Polish captions with AI** has the selected model fix misheard words, names and numbers before they're burned in.

## Smart framing (AutoClip / Auto Captions)
- YuNet face detection. Frames are decoded by ffmpeg with the same seek as the render, so tracking matches the output frame for frame.
- Each camera shot is handled separately (scene cuts are detected). Close-ups follow whoever is talking, scored by lip motion with hysteresis. Two people far apart in a wide shot become a top/bottom split screen. People who fit together are framed as a group.
- The camera eases within a shot and cuts hard on speaker or scene changes. The motion is rendered with ffmpeg `sendcmd` in a single pass.

## Requirements
- `ffmpeg`, Python 3.10+, and [`uv`](https://docs.astral.sh/uv/). `run.sh` creates `.venv` the first time it runs.
- Optional: an NVIDIA GPU, which is used automatically for Whisper and for NVENC encoding. VRAM is freed automatically:
  - Whisper is unloaded as soon as a full transcript is done.
  - When the job queue goes idle, Whisper and any Ollama models are unloaded. Back-to-back jobs keep them loaded so they don't reload each time.
  - The sidebar shows VRAM in use, and **free** unloads everything on demand.
- Optional: [Ollama](https://ollama.com) with a small model (`ollama pull qwen2.5:3b`). It powers AI moment picking and
  the "Write with AI" buttons. Without it, AutoClip falls back to the built-in heuristic scorer.
- Voices use Microsoft Edge's free online TTS (`edge-tts`), so generating voiceovers needs internet access. Everything else works offline.

## Tips
- Put a few long gameplay or "satisfying" clips in **Library → Backgrounds**. Story and text videos pick a random
  segment from them. Until you add some, a built-in animated gradient is used.
- Settings are environment variables: `CLIPLAND_WHISPER=medium` (more accurate, slower), `CLIPLAND_LLM=llama3.2:3b`,
  `PORT=9000`, `HOST=0.0.0.0` (to reach it from your phone on the LAN).
- All data lives in `data/` (`uploads`, `backgrounds`, `music`, `outputs`).
- Only import or clip content you own or have permission to use.

## Layout
```
app/main.py              FastAPI routes
app/jobs.py              persistent background job queue (1 worker, GPU-friendly)
app/transcribe.py        faster-whisper with word timestamps
app/moments.py           podcast moment finder (LLM + heuristic)
app/signals.py           gameplay/trailer highlight detection (audio, motion, cuts, reactions)
app/presets.py           AutoClip content types and their defaults
app/sources.py           link detection + yt-dlp downloads
app/gpu.py               VRAM status + unloading Whisper / Ollama models
app/reframe.py           speaker-aware 9:16 reframing (YuNet, shot detection, split screen)
app/captions.py          animated ASS caption styles
app/tts.py               edge-tts with word timings
app/llm.py               LLM providers: Ollama, Claude CLI, Anthropic API, OpenAI-compatible
app/settings.py          provider settings (data/settings.json)
app/pipelines/           autoclip, stories (story/texts/voiceover), tools, image renderers
static/                  no-build web UI (index.html, app.js, styles.css)
```

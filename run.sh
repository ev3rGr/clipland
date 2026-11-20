#!/usr/bin/env bash
# Clipland launcher. First run sets everything up (all free / open source).
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  command -v uv >/dev/null || { echo "Install uv first: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }
  uv venv .venv
  uv pip install --python .venv/bin/python -r requirements.txt
fi
command -v ffmpeg >/dev/null || { echo "ffmpeg is required: sudo apt install ffmpeg"; exit 1; }
if command -v ollama >/dev/null && ! ollama list 2>/dev/null | grep -q .; then
  echo "Tip: 'ollama pull qwen2.5:3b' enables AI moment picking and script writing."
fi
PORT="${PORT:-8000}"
echo "Clipland running at http://localhost:$PORT"
exec .venv/bin/uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "$PORT"

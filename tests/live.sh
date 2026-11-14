#!/bin/sh
# 会消耗少量额度；仅 Gemini、GPT、DeepSeek，各一次，无后备、无 Claude。GPT 没额度时：HUB_LIVE_SKIP=codex sh tests/live.sh
set -eu
cd "$(dirname "$0")/.."
exec python3 tests/live.py

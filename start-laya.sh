#!/usr/bin/env bash
# Start the local Laya decision server: GPU, localhost only, no network calls.
set -euo pipefail
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export LAYA_DEVICE="${LAYA_DEVICE:-cuda}"
export LAYA_PRELOAD=1
export LAYA_MODELS=typed-decisions
export LAYA_HOST=127.0.0.1
export LAYA_PORT="${LAYA_PORT:-8000}"
exec "$HOME/laya-env/bin/laya-serve"

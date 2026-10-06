#!/usr/bin/env bash
set -euo pipefail

# Give each service its own process group so cleanup also stops reloaders and Node.
set -m
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
service_pids=()

cleanup() {
  trap - EXIT INT TERM
  for pid in "${service_pids[@]}"; do
    kill -TERM -- "-$pid" 2>/dev/null || true
  done
  for pid in "${service_pids[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

printf '%s\n' 'Starting backend at http://localhost:8000 and Vue at http://localhost:5173.' 'Press Ctrl+C to stop both services.'
"${UV:-uv}" run --directory backend uvicorn app:app --reload --host 127.0.0.1 --port 8000 &
service_pids+=("$!")
"${PNPM:-pnpm}" --dir frontend dev --host 127.0.0.1 --port 5173 --strictPort &
service_pids+=("$!")

# If either service stops or fails, stop the other and preserve the exit status.
wait -n "${service_pids[@]}"

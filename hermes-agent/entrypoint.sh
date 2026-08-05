#!/bin/bash
set -e

echo "[Hermes Agent Entrypoint] Starting FastAPI Uvicorn Server on port 8000..."
uvicorn api_server:app --host 0.0.0.0 --port 8000 &

echo "[Hermes Agent Entrypoint] Starting Nostr Event Listener..."
exec python3 nostr_listener.py

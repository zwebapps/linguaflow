#!/usr/bin/env sh
# Free-tier entrypoint: API + ingestion worker in ONE container.
#
# Free plans give you a single always-on(ish) process, but the app needs two:
# the API only ENQUEUES uploads to Redis, and a worker consumes the queue —
# without it every upload sits at "pending / 0 chunks" forever. So the worker
# runs alongside uvicorn here; if either dies, the container exits and the
# platform restarts both. On paid/multi-service setups, run
# `python -m app.workers.ingest` as its own service instead.
set -e

python -m app.workers.ingest &
WORKER_PID=$!

# $PORT is what Render/Cloud Run inject; default keeps local docker runs easy.
uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" &
API_PID=$!

trap 'kill $WORKER_PID $API_PID 2>/dev/null' TERM INT

# Exit when EITHER process exits, so the platform notices and restarts.
wait -n $WORKER_PID $API_PID 2>/dev/null || wait $API_PID

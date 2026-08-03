#!/usr/bin/env bash
# Deploy the DeutschFlow API to Google Cloud Run.
#
#   1. gcloud auth login                 (once)
#   2. gcloud config set project <ID>    (once; billing must be enabled)
#   3. ./deploy/cloudrun.sh              (from the backend/ directory)
#
# Secrets live in deploy/.env.cloudrun (gitignored) — edit values there and
# rerun this script; nothing secret is committed or baked into the image.
# Rotating a credential = change the file, rerun.
set -euo pipefail

cd "$(dirname "$0")/.."
ENV_FILE="deploy/.env.cloudrun"
[ -f "$ENV_FILE" ] || { echo "Missing $ENV_FILE — see DEPLOYMENT.md"; exit 1; }

SERVICE="${SERVICE:-deutschflow-api}"
REGION="${REGION:-europe-west1}"

# --set-env-vars splits on commas; the ^##^ prefix switches the delimiter to
# a literal "##" so URLs and base64 secrets pass through untouched.
# (awk, not `paste -sd '##'` — paste cycles SINGLE-char delimiters.)
ENV_VARS="$(grep -Ev '^\s*(#|$)' "$ENV_FILE" | awk 'NR>1{printf "%s","##"} {printf "%s",$0} END{print ""}')"

exec gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --timeout 600 \
  --max-instances 2 \
  --set-env-vars "^##^${ENV_VARS}"

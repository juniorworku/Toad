#!/usr/bin/env bash
# Summarises a running engine's /api/overview, reading DEVICE_TOKEN from .env (never printed).
# Usage: overview.sh [base-url]   (default http://localhost:8787)
set -euo pipefail
cd "$(dirname "$0")/../../../.."
BASE=${1:-http://localhost:8787}
TOKEN=${DEVICE_TOKEN:-$(grep -E '^DEVICE_TOKEN=' .env 2>/dev/null | cut -d= -f2- || true)}
[[ -n $TOKEN ]] || { echo "DEVICE_TOKEN not found in the environment or .env" >&2; exit 1; }
curl -fsS -H "Authorization: Bearer $TOKEN" "$BASE/api/overview" | .venv/bin/python -c '
import json, sys
d = json.load(sys.stdin)
s, a = d["status"], d["agent"]
print(f"provider: {d.get(\"provider\", \"?\")}  device: {s[\"device\"]}  voice: {s[\"voice\"]}  "
      f"thinking: {s[\"thinking\"]}  calling: {s[\"calling\"]}")
print(f"agent: {a[\"name\"]} ({a[\"model\"]})  agentId: {a[\"agentId\"]}  session: {a[\"sessionId\"]}")
print(f"apps: {\"on\" if d[\"apps\"][\"enabled\"] else \"off\"}  away calls: {s[\"awayCalls\"] or \"off\"}")
print(f"focus: {(d[\"focus\"] or {}).get(\"task\", \"-\")}")
print(f"check-ins: {[c[\"about\"] for c in d[\"checkins\"]]}")
print(f"memories: {[m[\"text\"] for m in d[\"memories\"]]}")
print(f"pages: {len(d[\"pages\"])}  tools: {len(d[\"tools\"])}")
'

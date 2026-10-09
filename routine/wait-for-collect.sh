#!/usr/bin/env bash
# Wait until GitHub Actions in iizolenta-work has committed a pending.json collected after <since>.
# Usage: routine/wait-for-collect.sh <path to iizolenta-work> <since, YYYY-MM-DDTHH:MM:SSZ> [timeout seconds]
# Exit 0: fresh state/pending.json is in place. Exit 1: timed out (use whatever pending.json there is).
set -u
work=$1
since=$2
timeout=${3:-420}
deadline=$(( $(date +%s) + timeout ))
generated=""
while [ "$(date +%s)" -lt "$deadline" ]; do
  git -C "$work" pull -q --rebase origin main >/dev/null 2>&1
  generated=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get("generated_at") or "")' \
    "$work/state/pending.json" 2>/dev/null)
  # ISO timestamps in the same UTC format compare correctly as strings
  if [ -n "$generated" ] && [[ ! "$generated" < "$since" ]]; then
    echo "fresh pending.json: generated_at=$generated (since $since)"
    exit 0
  fi
  sleep 20
done
echo "no fresh pending.json after ${timeout}s (last generated_at: ${generated:-none})"
exit 1

#!/usr/bin/env bash
# Rebuild task/data/ (the agent's raw observational data, 1980-01 to 2014-12) from NOAA PSL.
# See README.md in this folder. Pass --dry-run to only list the sources.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
python3 "$HERE/download_data.py" --out "$HERE/../data" "$@"

#!/bin/bash
# Double-clickable macOS launcher for PG&E Statement Intelligence Dashboard
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "⚡ Launching PG&E Statement Intelligence Dashboard..."

# Prefer local .venv if available
if [ -f "$DIR/.venv/bin/python" ]; then
    PYTHON="$DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
else
    PYTHON="python"
fi

"$PYTHON" "$DIR/pge_intel.py"

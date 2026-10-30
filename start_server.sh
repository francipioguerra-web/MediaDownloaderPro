#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH"
export PYTHONUNBUFFERED=1
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# Kill any existing process on port 5555
lsof -ti:5555 | xargs kill -9 2>/dev/null
sleep 1

exec /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 server.py --port 5555

#!/bin/bash
# MediaDownloader Mac Native Launcher

# Read length-prefixed JSON input from stdin (Chrome Native Messaging Protocol)
read -n 4 length_bytes 2>/dev/null

# Read payload JSON
read -n 1024 payload 2>/dev/null

# Extract URL using python/grep if available
TARGET_URL=$(echo "$payload" | python3 -c "import sys, json; print(json.load(sys.stdin).get('url',''))" 2>/dev/null)

# Copy to clipboard via pbcopy
if [ -n "$TARGET_URL" ]; then
    echo -n "$TARGET_URL" | pbcopy
fi

# Launch Mac Desktop Application
open -a /Applications/MediaDownloader.app

# Send JSON response back to Chrome Native Messaging
RESPONSE='{"status":"ok","launched":true}'
LEN=${#RESPONSE}
python3 -c "import sys, struct; sys.stdout.buffer.write(struct.pack('I', $LEN)); sys.stdout.buffer.write(b'$RESPONSE')" 2>/dev/null

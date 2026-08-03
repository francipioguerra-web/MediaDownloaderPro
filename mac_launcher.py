#!/usr/bin/env python3
import sys
import struct
import json
import subprocess

def main():
    try:
        # Read 4-byte length prefix from stdin
        raw_length = sys.stdin.buffer.read(4)
        if not raw_length or len(raw_length) < 4:
            sys.exit(0)

        length = struct.unpack('@I', raw_length)[0]
        payload_bytes = sys.stdin.buffer.read(length)
        payload = json.loads(payload_bytes.decode('utf-8'))
        
        target_url = payload.get('url', '').strip()
        if target_url:
            with open('/tmp/mediadownloader_last_url.txt', 'w', encoding='utf-8') as f:
                f.write(target_url)

            # Copy to pbcopy
            try:
                proc = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
                proc.communicate(input=target_url.encode('utf-8'))
            except Exception:
                pass

            # Open or bring MediaDownloader.app to front
            try:
                subprocess.Popen(['open', '-a', '/Applications/MediaDownloader.app'])
            except Exception:
                pass

        # Respond to Chrome Native Messaging Host protocol
        response = json.dumps({'status': 'ok', 'launched': True}).encode('utf-8')
        sys.stdout.buffer.write(struct.pack('@I', len(response)))
        sys.stdout.buffer.write(response)
        sys.stdout.buffer.flush()

    except Exception:
        sys.exit(0)

if __name__ == '__main__':
    main()

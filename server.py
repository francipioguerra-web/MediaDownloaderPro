#!/usr/bin/env python3
"""
StreamingCommunity - Standalone Dedicated Server & Watch Party Hub
Esegue il server backend StreamingCommunity accessibile da rete locale (LAN) o Internet (Cloud/VPS/Tunnel),
consentendo a qualsiasi dispositivo (PC, Mac, iPhone, iPad, Android, Smart TV) di connettersi, guardare
e sincronizzare la riproduzione video in tempo reale (Watch Party).
"""

import os
import sys
import argparse
import socket

# Import the existing Flask app and Engine from app.py
from app import app, get_local_ip

def main():
    parser = argparse.ArgumentParser(description="StreamingCommunity Dedicated Web & Watch Party Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host address to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 5555)), help="Port to listen on (default: 5555)")
    parser.add_argument("--public-url", default=os.environ.get("PUBLIC_SERVER_URL", ""), help="Public Server URL (e.g. https://sc.yourdomain.com or ngrok/cloudflared url)")
    args = parser.parse_args()

    if args.public_url:
        os.environ["PUBLIC_SERVER_URL"] = args.public_url.rstrip("/")

    local_ip = get_local_ip()
    port = args.port

    print("=" * 65)
    print(" 🚀 STREAMINGCOMMUNITY DEDICATED SERVER & WATCH PARTY HUB")
    print("=" * 65)
    print(f"  • Accesso Locale (questo PC)    : http://127.0.0.1:{port}")
    print(f"  • Accesso Rete Locale (LAN)     : http://{local_ip}:{port}")
    if args.public_url:
        print(f"  • Accesso Remoto / Internet     : {args.public_url}")
    print(f"  • Interfaccia Smart TV / Cast   : http://{local_ip}:{port}/tv")
    print("=" * 65)
    print(" ⚡ Qualsiasi dispositivo sulla stessa rete Wi-Fi/LAN può connettersi")
    print(f"    aprendo semplicemente il browser su: http://{local_ip}:{port}")
    print("=" * 65)
    print(" Premi CTRL+C per arrestare il server.\n")

    app.run(host=args.host, port=port, debug=False, threaded=True)

if __name__ == "__main__":
    main()

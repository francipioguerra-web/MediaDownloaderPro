# MediaDownloader Pro - Estensione per Google Chrome

Estensione ufficiale per Google Chrome basata sull'engine di estrazione e download ad alta velocità di `app_fast.py` e `web_app.py`.

---

## 🚀 Caratteristiche Principali

- **Riconoscimento Automatico dell'URL Attivo**: rileva automaticamente il link aperto nella scheda del browser non appena apri l'estensione.
- **Sniffing di Flussi Multimediali HLS (.m3u8)**: intercetta in background i flussi video e le playlist frammentate.
- **Supporto Piattaforme**:
  - StreamingCommunity / Vixcloud (gestione automatica di token ed embed)
  - Bunkr (bunkr.sk, bunkr.cr, bunkr.is, bunkrr.org, ecc.)
  - Pixeldrain (download diretto multi-thread)
  - Flussi HLS / M3U8 generici
  - Piattaforme supportate da `yt-dlp` (YouTube, Vimeo, TikTok, Dailymotion, ecc.)
- **Selezione Qualità e Formato**: scelta tra MP4 (Full HD 1080p, 720p, 480p) e conversione audio in MP3 a 192kbps.
- **Avanzamento in Tempo Reale**: barra di progresso integrata nel popup con indicazione di velocità (MB/s) e MB scaricati.
- **Fallback Download Browser**: possibilità di avviare il download tramite il gestore di download nativo di Chrome.

---

## 📥 Come Installare l'Estensione in Google Chrome

1. Apri Google Chrome e digita nella barra degli indirizzi:
   `chrome://extensions/`
2. In alto a destra, attiva l'opzione **Modalità sviluppatore** (Developer mode).
3. Clicca sul pulsante **Carica estensione non impacchettata** (Load unpacked) situato in alto a sinistra.
4. Seleziona la cartella:
   `/Users/amministratore/Desktop/MediaDownloader/chrome_extension`
5. L'estensione **MediaDownloader Pro** comparirà nella lista ed è pronta all'uso!

---

## ⚡ Come Utilizzarla

1. **Avvia il Server Locale di MediaDownloader**:
   Esegui `web_app.py` dal terminale o avvia lo script di avvio:
   ```bash
   python3 web_app.py
   ```
   *(Il server sarà attivo su `http://localhost:5050`)*

2. **Naviga su qualsiasi sito video** nel tuo browser Chrome.
3. Clicca sull'icona di **MediaDownloader Pro** nella barra delle estensioni di Chrome.
4. L'estensione rileverà il video:
   - Seleziona la qualità desiderata (es. 1080p o MP3).
   - Clicca su **Scarica con MediaDownloader (Fast)**.
5. Il file verrà scaricato ad alta velocità nella tua cartella **Downloads**!

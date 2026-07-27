# 🌐 Media Downloader - Guida Web Application

La versione Web App di **Media Downloader** ti permette di usare l'applicazione da qualsiasi browser web ed inviarla a chiunque tramite un semplice link.

---

## 1. Come avviarla in Locale o sulla Rete Wi-Fi

1. Apri il terminale nella cartella del progetto:
   ```bash
   python3 web_app.py
   ```
2. L'applicazione si avvierà su due indirizzi:
   * **Sul tuo computer**: `http://localhost:5050`
   * **Per gli altri dispositivi nella stessa rete Wi-Fi**: `http://<IP-DEL-TUO-MAC>:5050` (es. `http://192.168.1.15:5050`)

Chiunque si colleghi al tuo Wi-Fi da iPhone, Android o altro PC potrà usare il downloader direttamente dal proprio browser!

---

## 2. Come pubblicarla Online per inviarla a CHIUNQUE nel Mondo

Per rendere la Web App accessibile a tutti via Internet (senza che debbano stare sul tuo stesso Wi-Fi), puoi caricarla gratuitamente su una piattaforma cloud in meno di 2 minuti.

### Opzione A: Deployment su Render.com (Gratuito)
1. Crea un account gratuito su [Render.com](https://render.com).
2. Clicca su **New +** -> **Web Service**.
3. Collega il tuo repository GitHub o carica la cartella del progetto.
4. Render rileverà automaticamente il `Dockerfile` o le dipendenze in `requirements.txt`:
   * **Start Command**: `gunicorn --bind 0.0.0.0:5000 web_app:app`
5. Clicca su **Create Web Service**. Otterrai un link del tipo `https://tuo-media-downloader.onrender.com` da condividere con chiunque!

### Opzione B: Deployment su Railway.app (Gratuito)
1. Vai su [Railway.app](https://railway.app).
2. Clicca su **New Project** -> **Deploy from GitHub repo** o **Docker**.
3. Railway compila il progetto ed in 60 secondi ti assegna un indirizzo pubblico `https://...up.railway.app`.

---

## 3. Funzionalità della Web App
* **Analisi dei link**: YouTube, StreamingCommunity, Vixcloud, flussi HLS `.m3u8` e link diretti.
* **Copia Link Stream**: Pulsante per copiare il flusso estrattore `.m3u8` o l'URL diretto.
* **Download Diretto su Dispositivo**: Quando il download sul server si completa, il destinatario può scaricare l'MP4 o l'MP3 sul proprio telefono/PC cliccando su **"Scarica su Dispositivo"**.
* **Controlli Pausa / Riprendi / Annulla**: Gestibili in tempo reale dal browser.

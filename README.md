# StreamingCommunity Web & Server

Web app avanzata per streaming, riproduzione video HLS con proxy integrato, ricerca catalogo e Watch Party sincronizzato in tempo reale.

## 🚀 Funzionalità
- **Web Player Integrato**: Player HLS con gestione automatica delle tracce audio (italiano/inglese), sottotitoli e selezione qualità (1080p, 720p, 480p, 360p).
- **Anteprima Scrubber Video**: Miniature durante lo scrub della barra temporale.
- **Continua a guardare & Sincronizzazione Profili**: Ripresa automatica al secondo esatto, cattura fotogramma di scena, supporto multi-profilo con PIN.
- **Interfaccia Cinema & Transizioni Frosted Glass**: Schermata di avvio in vetro satinato con copertina a tutto schermo e sincronizzazione del buffering.
- **Smart TV / Cast Interface**: Interfaccia dedicata su `/tv` ottimizzata per telecomandi e browser TV.
- **Watch Party in Tempo Reale**: Sincronizzazione live di play, pause e seek per guardare insieme a distanza.

---

## ☁️ Deploy su Render

1. Crea un nuovo **Web Service** su [Render.com](https://render.com).
2. Collega questa repository GitHub (`MediaDownloaderPro`).
3. Render rileverà automaticamente la configurazione o puoi inserire manualmente:
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn server:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120`
     *(oppure semplicemente: `python server.py`)*
4. Clicca su **Deploy Web Service**.

---

## 💻 Esecuzione Locale

```bash
# Installa le dipendenze
pip install -r requirements.txt

# Avvia il server dedicato
python server.py
```

Il server sarà accessibile su `http://localhost:5555`.

# StreamingCommunity

Sito web Python con catalogo, player HLS, profili, preferiti, cronologia e WatchParty.
Il servizio completo corrisponde al progetto avviato localmente sulla porta 5555.

## Pubblicazione su Render

1. Seleziona **New → Web Service** e collega la repository `francipioguerra-web/Streamingcommunity`.
2. Imposta:

   | Campo | Valore |
   | --- | --- |
   | Branch | `main` |
   | Language / Runtime | `Docker` |
   | Root Directory | lascia vuoto |
   | Dockerfile Path | `./Dockerfile` |
   | Docker Command | lascia vuoto: viene usato il comando già incluso |
   | Health Check Path | `/healthz` |

3. Scegli una regione vicina agli spettatori e premi **Deploy Web Service**.
4. Quando Render mostra il servizio come **Live**, apri il suo indirizzo HTTPS `onrender.com`.

Il Dockerfile installa Python, tutte le dipendenze e FFmpeg. Avvia `app:app` con
Gunicorn, un processo e 16 thread, compatibile con il WatchParty WebSocket.
La porta viene letta automaticamente dalla variabile `PORT` di Render.
Il sito online usa il proprio server WatchParty: non richiede tunnel o un secondo servizio.

È possibile anche usare **New → Blueprint**, collegando la repository: `render.yaml`
contiene già la configurazione del servizio completo.

### Profili e dati persistenti

Il piano Free è adatto a una prova: si sospende dopo 15 minuti senza traffico e non
supporta dischi persistenti. Profili e cronologia possono andare persi con riavvii e deploy.
Per conservarli, seleziona un'istanza a pagamento e aggiungi un **Persistent Disk**
con mount path `/app/data` (per esempio 1 GB).

Non sono inclusi profili, PIN, cronologia, credenziali o sessioni del computer locale.
Al primo accesso crea i profili dal sito.

### Variabili d'ambiente

Il Dockerfile configura già:

- `DATA_DIR=/app/data`
- `DOWNLOADS_DIR=/app/data/downloads`
- `WATCHPARTY_LOCAL_ONLY=1`

`TMDB_API_KEY` abilita loghi ufficiali e sfondi senza scritte: imposta una chiave TMDB nelle variabili Environment di Render.
`GEMINI_API_KEY` è facoltativa, per abilitare la chat AI.
L'accesso Google richiede credenziali OAuth proprie nelle variabili
`GOOGLE_CLIENT_ID` e `GOOGLE_CLIENT_SECRET`, con il callback del nuovo dominio.
Non inserire chiavi o dati personali nel repository.

I flussi video dipendono anche dalla disponibilità del fornitore e dalla sua
accessibilità dalla rete di Render; il deploy del sito non garantisce che il
fornitore accetti connessioni da un datacenter.

## Avvio locale

```bash
pip install -r requirements.txt
python server.py --port 5555
```

Apri `http://localhost:5555`. FFmpeg è richiesto per le funzioni di download.
Senza `DATA_DIR`, il progetto mantiene i percorsi locali dei profili già esistenti.

## Verifiche

```bash
python -m unittest discover -s tests -p '*_test.py'
node --test tests/player-continuity.test.cjs tests/player-replacement.test.cjs tests/watchparty-routing.test.cjs
```

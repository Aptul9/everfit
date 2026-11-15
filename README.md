# FitFuel

Dieta, allenamento, diario di quello che si mangia, bilancia Bluetooth e un assistente con l'intelligenza
artificiale, in un'app web da mettere sulla schermata Home del telefono (PWA). Più persone, ognuna con il suo
account e i suoi dati; un amministratore (il "capo") che crea gli account e può dare a ciascuno un piano scritto a mano.

Niente framework e niente build: il server è Python con la sola libreria standard, l'app è JavaScript, HTML e CSS
così come sono.

> **Questa è una copia ripulita.** Non contiene dati personali né credenziali: niente piani di persone vere, niente
> misure, niente indirizzi di server, niente chiavi. Il profilo del capo in `app/tools/build_plan.py` è un esempio, e
> l'unico piano scritto a mano è quello dell'account di prova (`app/server/piani/test.json`, dieta inventata).

## Com'è fatta

```
app/
├── public/               l'app: si serve così com'è
│   ├── index.html, sw.js, manifest.webmanifest, css/, icons/, img/ (foto dei piatti e degli esercizi)
│   ├── data/plan.json    il catalogo, uguale per tutti: cibi, ricette, esercizi, schede, settimana tipo (GENERATO)
│   └── js/               store.js (stato, conti, sincronizzazione), views/ (le schermate), personale.js (il piano
│                         calcolato dalle risposte del primo avvio), corpo.js (composizione corporea), bilancia.js, ...
├── server/               server.py (file, API, SQLite), accesso.py (account e cookie), cibo.py (servizi di AI,
│   │                     codici a barre), assistente.py (FitAI), parere.py, ponte.py (bilancia), spinta.py (notifiche)
│   └── piani/            i piani scritti a mano, uno per nome utente: <nome utente>.json (GENERATI)
├── tools/                build_plan.py (catalogo e piano del capo), persone.py (piani delle altre persone),
│   │                     make_icons.py, foto_piatti.py, prova_account.py
│   └── prove/            prove del server, della fila dell'AI, del ponte e delle notifiche; finta_gemini2.py (AI finta)
└── deploy/               docker-compose.yml e deploy.sh
desktop/                  l'app per PC con la bilancia Bluetooth e la "sentinella" (vedi desktop/README.md)
```

## Provarla in locale

Serve Python 3.12 (per `zoneinfo` e il resto della libreria standard; niente da installare).

```bash
cd app
python server/server.py --root public --data ../dati-prova --host 127.0.0.1 --port 8765
```

e poi `http://127.0.0.1:8765`. Senza `FIT_CODICE` non c'è nessun accesso: tutto è del capo.

Con gli account accesi, i dati in una cartella temporanea e l'AI dirottata su un servizio finto:

```bash
python tools/prove/finta_gemini2.py 8799      # in un terminale: l'AI finta (facoltativa)
python tools/prova_account.py                 # in un altro: http://localhost:8766, il capo entra con 1111 2222
```

## Il contenuto: catalogo e piani

`python tools/build_plan.py` scrive `public/data/plan.json` (il catalogo) e `server/piani/admin.json` (il piano del
capo: profilo, obiettivi, settimana, guida), poi chiama `tools/persone.py`, che scrive i piani scritti a mano per le
altre persone (qui solo `test.json`). `python tools/build_plan.py --check` stampa i totali di ogni giorno senza
scrivere niente.

- Chi ha un file in `server/piani/<nome utente>.json` riceve quel piano, sopra al catalogo.
- Gli altri rispondono alle domande del primo avvio e l'app calcola il loro piano (`public/js/personale.js`).
- Il nome del file del capo deve essere il suo nome utente: `admin` se non si imposta `FIT_UTENTE` o `FIT_NOME`.
- Ogni persona può poi cambiare pasti, grammi e piatti dall'app: le modifiche stanno nel suo stato (`mie`), non nei file.
- Un piano pronto per un nome utente senza account compare al capo come "account in attesa": basta scegliergli la password.

## Account e accesso

- Il primo account (id 1) è il capo: crea e toglie le altre persone da Piano → Persone e vede solo quando usano
  l'app, mai i loro dati. Le password stanno nel database come impasto PBKDF2.
- `FIT_CODICE`: il codice del capo (anche come password). Senza, il server non chiede niente (va bene solo in locale).
- `FIT_NOME`, `FIT_UTENTE`: nome e nome utente del capo (predefiniti "Admin" e `admin`).
- `FIT_COOKIE`: un vecchio cookie uguale per tutti, ancora accettato per chi passa dal percorso segreto.
- **Percorso segreto**: l'app per PC e la sentinella entrano come capo da un indirizzo segreto. Il reverse proxy
  aggiunge `X-Fit-Accesso: ok` alle richieste che arrivano da lì e toglie quell'intestazione a tutte le altre; per
  questo il container non va mai esposto direttamente. Un esempio per Caddy, da adattare:

```
fit.example.com {
    handle_path /<percorso-segreto>/* {
        request_header X-Fit-Accesso ok
        reverse_proxy fit:8080
    }
    handle {
        request_header -X-Fit-Accesso
        reverse_proxy fit:8080
    }
}
```

## Dati

Tutto in `<data>/fit.db` (SQLite in WAL): account, sessioni, stato dell'app di ciascuno (con una copia al giorno),
pesate, circonferenze, prodotti cercati per codice a barre, pareri dell'AI. Le chiavi dei servizi di AI le scrive
ogni persona nell'app e stanno in `<data>/chiavi/`. Nella cartella `data` e in `accesso.env` ci sono dati veri:
non vanno mai nel repository (vedi `.gitignore`).

## Intelligenza artificiale

Foto del piatto, parere sui prodotti scansionati e l'assistente FitAI, che risponde e fa le cose nell'app (segna i
pasti, cambia grammi e piatti, con il tasto per annullare). Ogni account usa la sua chiave; i servizi stanno in fila
e se uno non risponde si passa al successivo (`server/cibo.py`): Gemini, Mistral e un modello che gira in locale con
Ollama (facoltativo, servizio `ollama` nel compose). Le variabili utili:

| Variabile | A cosa serve |
|---|---|
| `FIT_MODELLO_GEMINI`, `FIT_GEMINI_CHAT`, `FIT_GEMINI_URL` | modello e indirizzo di Gemini; la chat usa il modello leggero (`leggero`) |
| `FIT_MODELLI_MISTRAL`, `FIT_MODELLI_MISTRAL_PICCOLI`, `FIT_MISTRAL_URL` | i modelli di Mistral in ordine di prova |
| `FIT_LOCALE_URL`, `FIT_MODELLO_LOCALE`, `FIT_LOCALE_*` | il modello locale (Ollama): indirizzo, modello, contesto, fili |
| `FIT_MODELLO_FOTO`, `FIT_AI_URL` | il servizio per le foto dei piatti |
| `FIT_ATTESA_*`, `FIT_SPINTA_AI`, `FIT_DOMANDE_ORA` | tempi massimi, sovrapposizione dei servizi, domande all'ora |
| `FIT_SITO` | l'indirizzo dell'app, usato come contatto nelle notifiche (VAPID) |
| `FIT_FUSO` | il fuso orario (predefinito `Europe/Rome`) |

Con un modello locale, ogni richiesta deve avere le stesse opzioni (contesto, lotto, fili), altrimenti Ollama
ricarica il modello e rilegge tutto da capo.

## Pubblicarla

`app/deploy/docker-compose.yml` è un esempio: il container `fit` (python:3.12-slim, file in sola lettura, dati in
`./data`, variabili da `./accesso.env`) dietro un reverse proxy sulla rete `proxy`, più il servizio facoltativo
`ollama`. `app/deploy/deploy.sh` rigenera i piani, copia `public` e `server` in `/opt/fit` sul server (alias ssh in
`FIT_SSH`, predefinito `fit-server`), fa una copia del database e riavvia solo `fit` quando cambia il server, poi
confronta le impronte dei file:

```bash
FIT_SSH=mio-server bash app/deploy/deploy.sh
```

Chi ha l'app sulla Home si aggiorna da solo alla prossima apertura: il server scrive versione ed elenco dei file
dentro `sw.js` mentre lo consegna.

## Prove

```bash
cd app
python tools/prove/prova_server.py . -        # il server con gli account (vuole l'AI finta sulla porta 8799)
python tools/prove/prova_catena.py            # la fila dei servizi di AI, con servizi finti
python tools/prove/prova_ponte.py             # il ponte tra telefono e sentinella
python tools/prove/prova_spinta.py            # la firma delle notifiche, contro OpenSSL
python ../desktop/bilancia.py prova           # il protocollo della bilancia, senza Bluetooth
```

Al 15/11/2026 tre controlli di `prova_server.py` sull'AI non tornano, anche nel progetto da cui viene questa copia:
la lunghezza delle istruzioni di base, il passaggio al modello di riserva e il ritorno a Gemini. Le prove non sono
state aggiornate quando la chat è passata subito al modello leggero di Gemini. Tutto il resto passa.

## Note

- La pagina non scorre: scorre `#app` dentro `#guscio`. Niente barre di scorrimento in vista, niente zoom; tema
  chiaro e scuro con variabili CSS.
- Il service worker nuovo non fa `skipWaiting` da solo: aspetta che la pagina gli dia il via.
- La firma nella schermata d'avvio e nella pagina d'accesso è quella di chi ha scritto l'app.

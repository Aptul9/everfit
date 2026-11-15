# FitFuel per PC

Due programmi per Windows, installati insieme:

- **FitFuel**: la stessa app del telefono in una finestra, con in più il collegamento Bluetooth alla bilancia
  (Runstar R5, modello FG2431WB, quella che si usa con l'app Starfit);
- **FitFuel bilancia**, la sentinella: sta tra le icone vicino all'orologio e fa le pesate chieste dal telefono.
  Il telefono da solo non può: Safari su iPhone non dà il Bluetooth alle pagine web.

Creati il 10/10/2026, quando l'app si chiamava Fit: il nome vecchio è rimasto dove cambiarlo avrebbe rotto qualcosa
(cartella `dev\fit`, file `fit_pc.pyw` e `fit.log`, la voce «Fit bilancia» nell'avvio di Windows e il collegamento
con lo stesso nome). Quello che si legge, cioè finestra, icona sul desktop, menu e avvisi, dice FitFuel.

La bilancia è dell'amministratore dell'app (il capo): entrambi i programmi entrano dal percorso segreto, che vale
come il suo account. Gli altri account non la vedono.

## Usarli

**Dal PC**: icona FitFuel sul desktop, Progressi → «Pesati ora», poi salire scalzi sulla bilancia e restare fermi
finché compare il risultato (da pochi secondi a una ventina: dipende da quanto Windows ci mette a collegarsi).

**Dal telefono**: stessa cosa dall'app sul telefono. Funziona se il PC di casa è acceso e sveglio, con il
Bluetooth attivo e la bilancia a portata (oppure il server con la sentinella Linux); la finestra di FitFuel può restare chiusa. Se il PC non risponde il
telefono lo dice e propone di segnare il peso a mano.

- Peso e impedenza arrivano dalla bilancia; grasso, muscolo, acqua e il resto li calcola l'app con le stesse
  formule di Starfit (`app/public/js/corpo.js`). Tutto viene salvato nel database del server.
- Le pesate fatte senza app restano nella memoria della bilancia e vengono importate alla pesata successiva,
  con la loro data. Quelle con un peso lontano più di 4 kg dal proprio vengono lasciate fuori (saranno di qualcun altro),
  ma la bilancia le cancella lo stesso.
- Se sul telefono c'è Starfit aperto va chiuso: la bilancia parla con un dispositivo alla volta.

### La sentinella

Parte da sola con Windows (voce «Fit bilancia» nella chiave `Run` dell'utente, si vede anche in
Gestione attività → App di avvio) e ogni volta che si apre FitFuel. Un clic sulla sua icona apre il menu:
stato, «Apri FitFuel», «Avvia con Windows» (si può togliere la spunta), «Tieni sveglio il PC in carica»,
«Apri il registro», «Esci».

**Il PC non si addormenta da solo quando è in carica.** Il PC di casa è un portatile con lo standby moderno: quando
nessuno lo usa si addormenta, e addormentato la sentinella è ferma e dal telefono non ci si pesa (lo dicono gli eventi di
Windows Kernel-Power 506 e 507). Per questo la sentinella, finché il PC è attaccato alla corrente, chiede a Windows di non addormentarlo
(`SetThreadExecutionState` con `ES_SYSTEM_REQUIRED`, nel filo `veglia`; si vede con `powercfg /requests`, alla voce
SYSTEM). Lo schermo si spegne lo stesso; chiudendo il coperchio o premendo il tasto di accensione si addormenta
come sempre; a batteria non chiede niente. L'opzione si spegne dal menu dell'icona e resta in `config.json`
(`sveglio`).
Windows 11 mette le icone nuove sotto la freccetta ^: si trascina fuori per averla sempre in vista.
Se è stata chiusa si riaccende aprendo FitFuel, oppure il collegamento `Fit bilancia` nella cartella di installazione.

### La sentinella su un server Linux

Le pesate chieste dal telefono le può fare anche un PC Linux sempre acceso (un server di casa) vicino alla
bilancia, invece del portatile, che quando non è in carica di notte si addormenta.

- `sentinella_linux.py`: la stessa sentinella senza icona, con `bilancia.py` così com'è (bleak su BlueZ). Si collega al
  Caddy del server (`"connetti": "127.0.0.1"`), quindi non passa dal DNS né dal router.
- `fit-bilancia.service` (systemd, utente `fitbilancia` nel gruppo `bluetooth`):
  - `Restart=always`, senza limite di tentativi: uccisa con `kill -9`, riparte in pochi secondi;
  - `WatchdogSec=180`: se si blocca e per tre minuti non si fa sentire, systemd la chiude (dopo 20 secondi) e la
    riapre. Con `faulthandler`, nel journal resta dove era ferma;
  - parte da sola all'accensione;
  - `bluetooth.service` va acceso e abilitato (lo fa l'installazione);
  - se il server non risponde (riavvio, pubblicazione) riprova dopo 1, 2 e 4 secondi, poi ogni 5. Il server è sullo
    stesso PC: allungare le attese fino a un minuto, come fa la sentinella del portatile, terrebbe il pallino rosso
    senza motivo.
- File sul server:
  - codice in `/opt/fit-bilancia`, con il `venv` e bleak 3.0.2, la versione del portatile;
  - configurazione in `/etc/fit-bilancia/config.json` (root:fitbilancia, 640): contiene il percorso segreto;
  - indirizzo della bilancia imparato in `/var/lib/fit-bilancia/stato.json`.
- Installare o aggiornare, dalla cartella del progetto in Git Bash: `FIT_SSH=<alias> bash desktop/installa_labpc.sh`. La prima volta prende
  la configurazione da quella del portatile, senza stampare l'indirizzo.
- Controllare:
  - `ssh <server> 'systemctl status fit-bilancia'` (la riga Status dice "in attesa" o "sto pesando");
  - `ssh <server> 'sudo journalctl -u fit-bilancia -n 50'`;
  - `ssh <server> 'sudo -u fitbilancia /opt/fit-bilancia/venv/bin/python /opt/fit-bilancia/sentinella_linux.py --prova'`.

**Una sentinella sola.** Se gira quella sul server, quella del portatile va spenta: si toglie dall'avvio di Windows
e in `config.json` si mettono:
- `"sentinella": false`: FitFuel per PC non la riaccende;
- `"avvio": false`: aperta a mano, non si rimette nell'avvio.

Resta installata come riserva e si riaccende con il collegamento `Fit bilancia`. Non tenerle accese tutte e due: si
contenderebbero le richieste, e la pesata andrebbe a chi arriva prima.

## Com'è fatta

```
desktop/
├── fit_pc.pyw      finestra (pywebview su WebView2) che apre l'app pubblicata e le offre la bilancia
├── sentinella.pyw  icona vicino all'orologio: raccoglie dal server le pesate chieste dal telefono e le esegue
├── sentinella_linux.py, fit-bilancia.service, installa_labpc.sh   la stessa sul server, come servizio systemd
├── bilancia.py     protocollo della bilancia e sessione Bluetooth (bleak)
├── comune.py       cartelle, configurazione e registro, usati da entrambi
├── installa.py     installa o aggiorna: ambiente Python, file, collegamenti, riaccende la sentinella
├── requisiti.txt   bleak, pywebview
├── fit.ico         GENERATA da app/tools/make_icons.py
└── strumenti/      ascolta.py e le registrazioni usate per capire il protocollo
```

Dentro FitFuel la pagina chiama `window.pywebview.api.misura(profilo)` e riceve gli avanzamenti su
`window.fitBilancia({fase, kg})`; il risultato è `{ok, peso, impedenza, memoria: [{quando, peso, impedenza}]}`.
Il resto lo fa `app/public/js/bilancia.js`.

La sentinella non ha finestra: chiede al server `GET api/bilancia/lavoro` (aspetta fino a 25 secondi, poi richiede)
e quando arriva una richiesta chiama la stessa `bilancia.misura()`, mandando avanzamenti e risultato con
`POST api/bilancia/notizie` (vedi `app/server/ponte.py`). L'icona è fatta con le API di Windows (ctypes), senza altre librerie.

## Installare o aggiornare

Serve Python 3.10 o più recente. La prima volta con l'indirizzo completo dell'app, poi senza argomenti:

```bash
python installa.py --url https://fit.example.com/<percorso segreto>/
```

Mette tutto nella cartella `dev\fit` del profilo utente: `venv`, `app` (i file qui sopra), `config.json`,
il collegamento `Fit bilancia`, `fit.log`, `sentinella.log`, `web` (cookie e copia per l'uso senza rete),
crea l'icona FitFuel sul desktop (se c'è ancora quella vecchia, «Fit», le cambia nome) e riaccende la sentinella.

Non in AppData: i programmi installati dallo Store, come Claude, ne vedono una copia loro, e un'installazione
lanciata da lì non si ritroverebbe aprendo l'app dal desktop. Per lo stesso motivo l'installatore accende la
sentinella passando da Esplora risorse (`explorer.exe` sul collegamento): così gira come se l'avessi aperta tu
e l'iscrizione all'avvio di Windows finisce nel posto giusto. Una sentinella lanciata da dentro un programma
dello Store se ne accorge (`appdata_privata()`) e non tocca l'avvio automatico.

Dopo una modifica ai file di questa cartella basta rilanciare `installa.py` (riaccende da solo la sentinella)
e riaprire FitFuel. Le modifiche alla parte web arrivano da sole con `bash deploy/deploy.sh` (cartella `app`).

## Controlli

```bash
python bilancia.py prova
```

rifà a tavolino una sessione d'esempio, senza Bluetooth.

Dalla cartella di installazione, con il Python del `venv`:

```bash
venv\Scripts\python.exe app\fit_pc.pyw --prova
```

apre la finestra, controlla pagina, ponte con la bilancia e Bluetooth del PC, e chiude. Stampa l'esito in JSON.

```bash
venv\Scripts\python.exe app\sentinella.pyw --prova
```

dice se il server risponde, se vede la sentinella accesa, se il Bluetooth funziona e se l'avvio automatico è registrato.

Se qualcosa non va, `fit.log` (l'app) e `sentinella.log` (la sentinella) dicono cosa è successo.
Con `"dettagli": true` in `config.json` ci finiscono anche ogni pacchetto della bilancia
e i passi del collegamento.

## Protocollo della bilancia

La bilancia si accende salendoci e annuncia il servizio `FFB0`. Si scrive su `FFB1`, le risposte arrivano come
notifiche su `FFB2`. Ogni pacchetto è lungo 20 byte: `AC 27`, 16 byte di corpo, tipo, somma dei byte 2..18.

| Tipo | Verso | Contenuto |
|---|---|---|
| `D5` | bilancia → PC | peso in diretta: grammi nei 18 bit bassi dei byte 3..5; byte 2 & 0x80 = peso fermo |
| `D6` | bilancia → PC | risultato: impedenza in ohm nei byte 4..5, peso nei byte 8..10 |
| `D8` | bilancia → PC | pesata in memoria: ora unix nei byte 3..6, peso 8..10, impedenza 15..16 |
| `D0` | PC → bilancia | ora e profilo: ora unix, `08 00 00`, altezza, `00 00`, età, sesso (1 uomo, 2 donna), `00 00`, `03` |
| `DF` | PC → bilancia | `01` = avvio della sessione, `04 xx` = conferma del pacchetto di tipo `xx` |

Senza profilo e avvio la bilancia manda solo il peso e dopo qualche secondo chiude: l'impedenza arriva solo a
sessione avviata. `D6` e `D8` vanno confermati; una pesata in memoria confermata sparisce dalla bilancia.
Nei pacchetti della bilancia contano solo i 5 bit bassi della somma.

Il protocollo `AC 02` da 8 byte che si trova in giro per le Runstar è di un'altra revisione: questa lo ignora.
La struttura dei pacchetti viene dal progetto openScale (gestore `TaylorBIA`), usato come documentazione;
le formule della composizione corporea sono state ricavate dalla libreria dell'app Starfit e verificate
sui valori mostrati dall'app con la stessa pesata.

## Cose da sapere

- Il primo collegamento dopo essere saliti può richiedere più di dieci secondi (13 nella prova del 10/10/2026,
  2 nelle prove del mattino con lo stesso PC). La bilancia intanto pesa e aspetta; se si spegne prima, la pesata
  resta nella sua memoria e arriva alla successiva.
- Il Bluetooth gira in un thread suo: su Windows non deve stare nel thread della finestra.
- Una sola finestra di FitFuel e una sola sentinella alla volta: la seconda apertura non fa niente (FitFuel porta davanti la prima).
- Dal telefono la pesata funziona solo con il PC acceso e non in sospensione. La sentinella non può svegliarlo, ma
  finché è in carica non lo lascia addormentare da solo (vedi «La sentinella»): restano il coperchio chiuso, il tasto
  di accensione e la batteria. Per questo la sentinella può girare anche su un server Linux sempre acceso.

#!/usr/bin/env python3
"""Pesata con la bilancia Runstar R5 (iComon, modello FG2431WB) via Bluetooth LE.

    python bilancia.py prova                 ricontrolla il protocollo sui pacchetti registrati, senza Bluetooth
    python bilancia.py radio                 dice se il Bluetooth del PC risponde (non si collega a niente)
    python bilancia.py pesa m,30,175 [s]     aspetta la bilancia (s secondi) e fa una pesata vera

La bilancia si accende quando ci sali e annuncia il servizio FFB0. Si scrive su FFB1, le risposte arrivano
come notifiche su FFB2. Ogni pacchetto e' lungo 20 byte:

    AC 27 | 16 byte di corpo | tipo | somma dei byte 2..18

    D5  bilancia -> PC   peso in diretta: grammi nei 18 bit bassi dei byte 3..5, byte 2 & 0x80 = peso fermo
    D6  bilancia -> PC   risultato: impedenza in ohm nei byte 4..5, peso nei byte 8..10
    D8  bilancia -> PC   pesata rimasta in memoria: ora unix nei byte 3..6, peso 8..10, impedenza 15..16
    D0  PC -> bilancia   ora e profilo: ora unix, 08 00 00, altezza, 00 00, eta', sesso (1 uomo, 2 donna), 00 00, 03
    DF  PC -> bilancia   01 = avvio della sessione, 04 xx = conferma del pacchetto di tipo xx

Nei pacchetti della bilancia contano solo i 5 bit bassi della somma. Senza profilo e avvio la bilancia manda
soltanto il peso in diretta e dopo qualche secondo chiude: l'impedenza arriva solo a sessione avviata.
D6 e D8 vanno confermati; una pesata in memoria confermata sparisce dalla bilancia.
"""
import asyncio
import json
import logging
import queue
import sys
import threading
import time

SERVIZIO = "0000ffb0-0000-1000-8000-00805f9b34fb"
SCRITTURA = "0000ffb1-0000-1000-8000-00805f9b34fb"
NOTIFICHE = "0000ffb2-0000-1000-8000-00805f9b34fb"

PESO_MINIMO = 2.0          # kg: sotto, sulla bilancia non c'e' nessuno
ATTESA_IMPEDENZA = 12.0    # s dopo il peso fermo: se il risultato non arriva ci si accontenta del peso
CODA_MEMORIA = 1.5         # s dopo il risultato: il tempo di ricevere le pesate rimaste in memoria
DURATA_MASSIMA = 75.0      # s: oltre, il collegamento si chiude comunque
ANNO_2020 = 1577836800

NON_TROVATA = ("Non ho trovato la bilancia. Sali per accenderla (sul display deve comparire il peso) e riprova. "
               "Se sul telefono c'e' Starfit aperto chiudilo: la bilancia parla con un dispositivo alla volta.")
SCOLLEGATA = "La bilancia si e' scollegata prima di finire. Risali e resta fermo finche' non compare il risultato."
BLUETOOTH = "Il Bluetooth del PC e' spento o non risponde: accendilo dalle impostazioni di Windows e riprova."
IMPREVISTO = "Qualcosa e' andato storto con il Bluetooth. Riprova; se succede ancora guarda il file fit.log."

log = logging.getLogger("fit.bilancia")


class Annullata(Exception):
    """La pesata e' stata interrotta da chi l'aveva chiesta."""


def pacchetto(corpo, tipo):
    corpo = bytes(corpo) + bytes(16 - len(corpo))
    grezzo = bytes([0xAC, 0x27]) + corpo + bytes([tipo])
    return grezzo + bytes([sum(grezzo[2:19]) & 0xFF])


def profilo_ora(sesso, eta, altezza, ora=None):
    corpo = bytearray(16)
    corpo[0:4] = int(time.time() if ora is None else ora).to_bytes(4, "big")
    corpo[4] = 0x08
    corpo[7] = max(100, min(220, int(altezza)))
    corpo[10] = max(10, min(99, int(eta)))
    corpo[11] = 2 if str(sesso).lower().startswith("f") else 1
    corpo[14] = 0x03
    return pacchetto(corpo, 0xD0)


AVVIO = pacchetto([0x01], 0xDF)


def conferma(tipo):
    return pacchetto([0x04, tipo], 0xDF)


def valido(dati):
    return len(dati) == 20 and dati[0] == 0xAC and dati[1] == 0x27 and (sum(dati[2:19]) ^ dati[19]) & 0x1F == 0


def chili(tre_byte):
    return (int.from_bytes(tre_byte, "big") & 0x3FFFF) / 1000


class Pesata:
    """Segue una pesata pacchetto per pacchetto: non sa niente di Bluetooth, cosi' si puo' provare a tavolino."""

    def __init__(self, evento=None, orologio=time.monotonic):
        self.evento = evento or (lambda fase, kg=None: None)
        self.ora = orologio
        self.kg = None
        self.fermo = None
        self.t_fermo = 0.0
        self.finale = None
        self.t_ultimo = 0.0
        self.memoria = []

    def arrivo(self, dati):
        """Legge un pacchetto e restituisce quelli da scrivere in risposta."""
        dati = bytes(dati)
        if not valido(dati):
            log.info("pacchetto ignorato: %s", dati.hex())
            return []
        tipo = dati[18]
        if tipo == 0xD5:
            self._diretta(chili(dati[3:6]), bool(dati[2] & 0x80))
        elif tipo == 0xD6:
            kg = chili(dati[8:11]) or self.fermo or self.kg
            ohm = int.from_bytes(dati[4:6], "big")
            if kg and kg >= PESO_MINIMO:
                self.finale = (kg, ohm or None)
                self.t_ultimo = self.ora()
                log.info("risultato: %.2f kg, %s ohm", kg, ohm or "-")
            return [conferma(tipo)]
        elif tipo == 0xD8:
            quando = int.from_bytes(dati[3:7], "big")
            kg = chili(dati[8:11])
            ohm = int.from_bytes(dati[15:17], "big")
            self.t_ultimo = self.ora()
            # con l'orologio mai regolato (pile appena cambiate) la data non dice niente: la pesata si scarta
            if kg >= PESO_MINIMO and ANNO_2020 <= quando <= time.time() + 86400:
                voce = {"quando": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(quando)), "peso": round(kg, 2), "impedenza": ohm or None}
                if voce not in self.memoria:
                    self.memoria.append(voce)
                log.info("in memoria: %s %.2f kg, %s ohm", voce["quando"], kg, ohm or "-")
            else:
                log.info("pesata in memoria scartata: ora %d, %.2f kg", quando, kg)
            return [conferma(tipo)]
        return []

    def _diretta(self, kg, fermo):
        if self.finale:
            return
        if kg < PESO_MINIMO:
            self.kg = self.fermo = None
            return
        if not fermo:
            # dopo un peso fermo: si e' mosso e la bilancia sta ripesando
            self.fermo = None
            if kg != self.kg:
                self.evento("peso", round(kg, 2))
        elif kg != self.fermo:
            self.fermo = kg
            self.t_fermo = self.ora()
            self.evento("impedenza", round(kg, 2))
        self.kg = kg

    def finita(self):
        if self.finale:
            return self.ora() - self.t_ultimo >= CODA_MEMORIA
        if self.fermo is not None:
            return self.ora() - self.t_fermo >= ATTESA_IMPEDENZA
        return False

    def esito(self):
        if self.finale:
            kg, ohm = self.finale
        elif self.fermo is not None:
            kg, ohm = self.fermo, None
        elif self.memoria:
            kg, ohm = None, None
        else:
            return None
        return {"ok": True, "peso": round(kg, 2) if kg else None, "impedenza": ohm, "memoria": list(self.memoria)}


async def _cerca(indirizzo, secondi, stop):
    """Aspetta che la bilancia si faccia sentire. None se il tempo finisce."""
    from bleak import BleakScanner

    trovata = asyncio.get_running_loop().create_future()

    def visto(dev, adv):
        if trovata.done():
            return
        servizi = [u.lower() for u in (adv.service_uuids or [])]
        if SERVIZIO in servizi or (indirizzo and dev.address.upper() == indirizzo.upper()):
            log.info("bilancia in vista: %s rssi %s", dev.address, adv.rssi)
            trovata.set_result(dev)

    async with BleakScanner(visto):
        fine = time.monotonic() + secondi
        while time.monotonic() < fine:
            if stop.is_set():
                raise Annullata()
            if trovata.done():
                return trovata.result()
            await asyncio.sleep(0.2)
    return trovata.result() if trovata.done() else None


async def _pesa(dev, profilo, evento, stop):
    """Si collega, avvia la sessione e segue la pesata. None se nessuno e' rimasto fermo sulla bilancia."""
    from bleak import BleakClient

    coda = asyncio.Queue()
    caduta = asyncio.Event()
    st = Pesata(evento)
    inizio = time.monotonic()
    try:
        # Windows a volte ci mette piu' di dieci secondi a collegarsi: la bilancia intanto pesa e aspetta
        async with BleakClient(dev, timeout=20.0, disconnected_callback=lambda _c: caduta.set()) as c:
            collegata = time.monotonic()
            await c.start_notify(NOTIFICHE, lambda _ch, dati: coda.put_nowait(bytes(dati)))
            for p in (profilo_ora(**profilo), AVVIO, profilo_ora(**profilo)):
                await c.write_gatt_char(SCRITTURA, p, response=True)
                await asyncio.sleep(0.12)
            log.info("collegata in %.1f s, sessione avviata in altri %.1f s", collegata - inizio, time.monotonic() - collegata)
            evento("collegata")
            fine = time.monotonic() + DURATA_MASSIMA
            while not st.finita() and time.monotonic() < fine:
                if stop.is_set():
                    raise Annullata()
                try:
                    dati = await asyncio.wait_for(coda.get(), 0.25)
                except asyncio.TimeoutError:
                    if caduta.is_set():
                        log.info("la bilancia ha chiuso il collegamento")
                        break
                    continue
                log.debug("<< %s", dati.hex())
                for risposta in st.arrivo(dati):
                    await c.write_gatt_char(SCRITTURA, risposta, response=True)
    except Annullata:
        raise
    except Exception as e:
        # il collegamento puo' cadere mentre si conferma o si chiude: quello che e' gia' arrivato vale lo stesso
        if st.esito() is None:
            raise
        log.info("collegamento chiuso male, pesata gia' letta: %r", e)
    return st.esito()


async def _sessione(profilo, evento, stop, indirizzo, attesa):
    fine = time.monotonic() + attesa
    falliti = 0
    vista = False
    while True:
        resto = fine - time.monotonic()
        if resto <= 0:
            return {"ok": False, "errore": SCOLLEGATA if vista else NON_TROVATA}
        evento("cerca")
        try:
            dev = await _cerca(indirizzo, resto, stop)
        except Annullata:
            raise
        except Exception:
            log.exception("la ricerca Bluetooth non parte")
            return {"ok": False, "errore": BLUETOOTH}
        if dev is None:
            return {"ok": False, "errore": SCOLLEGATA if vista else NON_TROVATA}
        evento("trovata")
        try:
            esito = await _pesa(dev, profilo, evento, stop)
        except Annullata:
            raise
        except Exception as e:
            falliti += 1
            log.warning("collegamento fallito (%d): %r", falliti, e)
            if falliti >= 4:
                return {"ok": False, "errore": SCOLLEGATA}
            await asyncio.sleep(0.5)
            continue
        if esito:
            esito["indirizzo"] = dev.address
            return esito
        # collegata, ma nessuno e' rimasto fermo sopra: si riparte, lasciando il tempo di risalire
        vista = True
        fine = max(fine, time.monotonic() + 25)


def misura(profilo, evento=None, stop=None, indirizzo=None, attesa=90.0):
    """Fa una pesata e torna quando e' finita.

    profilo   {"sesso": "m"|"f", "eta": anni, "altezza": cm}
    evento    chiamata come evento(fase, kg) nel thread di chi chiama; fasi: cerca, trovata, collegata, peso, impedenza
    stop      threading.Event: impostarlo interrompe la pesata
    Risultato {"ok": True, "peso": kg, "impedenza": ohm o None, "memoria": [{quando, peso, impedenza}], "indirizzo"}
              oppure {"ok": False, "errore": testo}.
    Il Bluetooth gira in un thread suo: su Windows non deve stare nel thread della finestra.
    """
    stop = stop or threading.Event()
    profilo = {"sesso": profilo.get("sesso", "m"), "eta": profilo.get("eta", 30), "altezza": profilo.get("altezza", 170)}
    eventi = queue.Queue()
    esito = {}

    def lavoro():
        try:
            esito.update(asyncio.run(_sessione(profilo, lambda fase, kg=None: eventi.put((fase, kg)), stop, indirizzo, attesa)))
        except Annullata:
            esito.update(ok=False, annullata=True, errore="Pesata annullata.")
        except Exception:
            log.exception("pesata fallita")
            esito.update(ok=False, errore=IMPREVISTO)
        finally:
            eventi.put(None)

    threading.Thread(target=lavoro, name="bilancia", daemon=True).start()
    while True:
        voce = eventi.get()
        if voce is None:
            break
        if evento:
            try:
                evento(*voce)
            except Exception:
                log.exception("evento non consegnato")
    return esito


def radio_pronta(secondi=3.0):
    """Dice se il Bluetooth del PC risponde: tiene accesa la ricerca per qualche secondo, senza collegarsi a niente."""
    esito = {}

    async def ascolta():
        from bleak import BleakScanner

        vicini = set()
        async with BleakScanner(lambda dev, adv: vicini.add(dev.address)):
            await asyncio.sleep(secondi)
        return len(vicini)

    def lavoro():
        try:
            esito.update(ok=True, vicini=asyncio.run(ascolta()))
        except Exception as e:
            log.exception("il Bluetooth non risponde")
            esito.update(ok=False, errore=repr(e))

    filo = threading.Thread(target=lavoro, name="bilancia", daemon=True)
    filo.start()
    filo.join(secondi + 15)
    return esito or {"ok": False, "errore": "nessuna risposta"}


def prova():
    """Rifa' a tavolino una sessione d'esempio, con pacchetti fatti come quelli veri: 72,55 kg, 480 ohm, una pesata in memoria."""
    assert profilo_ora("m", 30, 175, ora=0x6ACA0608).hex() == "ac276aca0608080000af00001e0100000300d0eb"
    assert AVVIO.hex() == "ac2701000000000000000000000000000000dfe0"
    assert conferma(0xD6).hex() == "ac2704d60000000000000000000000000000dfb9"
    assert conferma(0xD8).hex() == "ac2704d80000000000000000000000000000dfbb"

    tempo = [0.0]
    eventi = []
    st = Pesata(lambda fase, kg=None: eventi.append((fase, kg)), orologio=lambda: tempo[0])
    h = bytes.fromhex
    assert st.arrivo(h("ac2700691ad0000000000000000000000002d52a")) == []
    assert st.arrivo(h("ac2700691ad0000000000000000000000002d52a")) == []
    assert st.arrivo(h("ac2700691ad0000000000000000000000002d52b")) == [], "somma sbagliata: va ignorato"
    assert st.arrivo(h("ac2780691b66000000000000000000000002d521")) == []
    assert eventi == [("peso", 72.4), ("impedenza", 72.55)], eventi
    tempo[0] = 3.0
    assert not st.finita()
    assert st.arrivo(h("ac27010001e00180691b6600000000000002d605")) == [conferma(0xD6)]
    tempo[0] = 3.4
    assert st.arrivo(h("ac27006aca053b806919a40000000101e502d85b")) == [conferma(0xD8)]
    tempo[0] = 4.0
    assert not st.finita()
    tempo[0] = 5.0
    assert st.finita()
    atteso = {"ok": True, "peso": 72.55, "impedenza": 480,
              "memoria": [{"quando": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(0x6ACA053B)), "peso": 72.1, "impedenza": 485}]}
    assert st.esito() == atteso, st.esito()

    # senza risultato (calze, piedi fuori dai dischi) dopo un po' resta il solo peso
    st = Pesata(orologio=lambda: tempo[0])
    st.arrivo(h("ac2780691b66000000000000000000000002d521"))
    tempo[0] += ATTESA_IMPEDENZA - 1
    assert not st.finita()
    tempo[0] += 2
    assert st.finita() and st.esito() == {"ok": True, "peso": 72.55, "impedenza": None, "memoria": []}

    # nessuno sopra: niente da riferire
    assert Pesata().esito() is None
    print("protocollo a posto:", json.dumps(atteso, ensure_ascii=False))


def main():
    for flusso in (sys.stdout, sys.stderr):
        flusso.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) > 1 and sys.argv[1] == "prova":
        prova()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "radio":
        print(json.dumps(radio_pronta(), ensure_ascii=False))
        return
    if len(sys.argv) > 2 and sys.argv[1] == "pesa":
        logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(message)s", stream=sys.stderr)
        logging.getLogger("bleak").setLevel(logging.WARNING)
        sesso, eta, altezza = sys.argv[2].split(",")
        attesa = float(sys.argv[3]) if len(sys.argv) > 3 else 90.0
        print("sali sulla bilancia...", flush=True)
        esito = misura({"sesso": sesso, "eta": int(eta), "altezza": int(altezza)},
                       evento=lambda fase, kg=None: print("  ", fase, "" if kg is None else kg, flush=True), attesa=attesa)
        print(json.dumps(esito, ensure_ascii=False, indent=1))
        return
    print(__doc__)


if __name__ == "__main__":
    main()

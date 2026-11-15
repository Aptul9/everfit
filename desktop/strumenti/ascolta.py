#!/usr/bin/env python3
"""Ascolta la bilancia: registra annunci Bluetooth e notifiche GATT, per capire o ricontrollare il protocollo.

    ascolta.py scan [secondi]                 elenca i dispositivi BLE nei dintorni
    ascolta.py auto [attesa] [ascolto]        aspetta che compaia una bilancia, si collega e registra
    ascolta.py ascolta <indirizzo> [secondi]  si collega, mostra servizi e registra tutto quello che arriva
    ascolta.py ascolta <indirizzo> [secondi] --scrivi ffb1=HEX[,HEX...]   manda anche dei comandi

Tutto finisce anche in un file .jsonl accanto allo script (cartella registrazioni/).
"""
import argparse
import asyncio
import json
import os
import sys
import time

from bleak import BleakClient, BleakScanner

QUI = os.path.dirname(os.path.abspath(__file__))
REG = os.path.join(QUI, "registrazioni")
INDIZI = ("ffb0", "fff0", "ffe0", "181b", "181d")
NOMI = ("icomon", "swan", "runstar", "starfit", "fg2", "fitdays", "scale", "lefu", "yg", "qn-", "body")


def hx(b):
    return bytes(b).hex()


def ac02(b2, b3=0, b4=0, b5=0):
    """Comando da 8 byte della famiglia iComon: AC 02 + quattro byte + CC + somma."""
    corpo = [b2 & 0xFF, b3 & 0xFF, b4 & 0xFF, b5 & 0xFF, 0xCC]
    return bytes([0xAC, 0x02] + corpo + [sum(corpo) & 0xFF]).hex()


def ac27(corpo, tipo):
    """Pacchetto da 20 byte del protocollo AC 27: AC 27 + 16 byte + tipo + somma dei byte 2..18."""
    corpo = bytes(corpo) + bytes(16 - len(corpo))
    grezzo = bytes([0xAC, 0x27]) + corpo + bytes([tipo])
    return (grezzo + bytes([sum(grezzo[2:19]) & 0xFF])).hex()


def profilo_ac27(sesso, eta, altezza):
    """Profilo e ora (tipo D0): ora unix, 08 00 00, altezza, 00 00, eta', sesso, 00 00, 03."""
    corpo = bytearray(16)
    corpo[0:4] = int(time.time()).to_bytes(4, "big")
    corpo[4] = 0x08
    corpo[7] = altezza
    corpo[10] = eta
    corpo[11] = 1 if sesso == "m" else 2
    corpo[14] = 0x03
    return ac27(corpo, 0xD0)


def saluto_ac27(sesso, eta, altezza):
    """Quello che scrive l'app ufficiale: profilo, avvio sessione (DF 01), di nuovo profilo."""
    return [profilo_ac27(sesso, eta, altezza), ac27([0x01], 0xDF), profilo_ac27(sesso, eta, altezza)]


def saluto_runstar(sesso, eta, altezza):
    """Sequenza di avvio della Runstar R5: profilo, data, ora, unita' in kg."""
    ora = time.localtime()
    return [
        ac02(0xF7), ac02(0xFA),
        ac02(0xFB, 1 if sesso == "m" else 2, eta, altezza),
        ac02(0xFD, ora.tm_year - 2000, ora.tm_mon, ora.tm_mday),
        ac02(0xFC, ora.tm_hour, ora.tm_min, ora.tm_sec),
        ac02(0xFE, 0x06, 0x00, 0x00),
    ]


class Registro:
    def __init__(self, nome):
        os.makedirs(REG, exist_ok=True)
        self.percorso = os.path.join(REG, time.strftime("%Y%m%d-%H%M%S") + "-" + nome + ".jsonl")
        self.f = open(self.percorso, "w", encoding="utf-8")
        self.t0 = time.time()

    def scrivi(self, **voce):
        voce["t"] = round(time.time() - self.t0, 3)
        self.f.write(json.dumps(voce, ensure_ascii=False) + "\n")
        self.f.flush()


async def scan(secondi):
    visti = {}

    def visto(dev, adv):
        v = visti.setdefault(dev.address, {"n": 0, "pacchetti": set()})
        v["n"] += 1
        v["nome"] = adv.local_name or dev.name or v.get("nome") or ""
        v["rssi"] = adv.rssi
        v["servizi"] = sorted(set(v.get("servizi", [])) | set(adv.service_uuids or []))
        for k, d in (adv.manufacturer_data or {}).items():
            v["pacchetti"].add("mfr %04x: %s" % (k, hx(d)))
        for k, d in (adv.service_data or {}).items():
            v["pacchetti"].add("svc %s: %s" % (k[4:8], hx(d)))

    async with BleakScanner(visto):
        await asyncio.sleep(secondi)

    reg = Registro("scan")
    righe = sorted(visti.items(), key=lambda kv: -(kv[1].get("rssi") or -999))
    print("%d dispositivi in %ds" % (len(righe), secondi))
    for addr, v in righe:
        brevi = [s[4:8] for s in v["servizi"]]
        nome = v["nome"]
        sospetto = any(i in brevi for i in INDIZI) or any(n in nome.lower() for n in NOMI)
        reg.scrivi(tipo="annuncio", indirizzo=addr, nome=nome, rssi=v["rssi"], servizi=brevi, pacchetti=sorted(v["pacchetti"]), n=v["n"])
        print("%s %s  rssi %4s  n=%-3d %-22s servizi=%s" % ("*" if sospetto else " ", addr, v["rssi"], v["n"], nome[:22] or "-", ",".join(brevi) or "-"))
        for p in sorted(v["pacchetti"])[:4]:
            print("      " + p[:110])
    print("registro:", reg.percorso)


async def auto(attesa, secondi, scritture):
    """Aspetta un dispositivo che sembra una bilancia (servizio ffb0 o nome noto) e lo ascolta."""
    trovato = asyncio.get_running_loop().create_future()
    vicini = {}

    def visto(dev, adv):
        brevi = [u[4:8] for u in (adv.service_uuids or [])]
        nome = adv.local_name or dev.name or ""
        dati = ["mfr %04x: %s" % (k, hx(d)) for k, d in (adv.manufacturer_data or {}).items()]
        dati += ["svc %s: %s" % (k[4:8], hx(d)) for k, d in (adv.service_data or {}).items()]
        v = vicini.setdefault(dev.address, {"nome": nome, "rssi": adv.rssi, "servizi": brevi, "dati": set()})
        v["rssi"] = adv.rssi
        v["nome"] = nome or v["nome"]
        v["dati"].update(dati)
        forte = "ffb0" in brevi or any(n in nome.lower() for n in ("icomon", "swan", "runstar", "fg2", "fitdays", "lefu"))
        if forte and not trovato.done():
            print("bilancia in vista: %s %r servizi=%s rssi=%s %s" % (dev.address, nome, brevi, adv.rssi, dati), flush=True)
            trovato.set_result((dev, nome))

    print("aspetto la bilancia per %ds: sali adesso..." % attesa, flush=True)
    async with BleakScanner(visto):
        try:
            dev, nome = await asyncio.wait_for(trovato, attesa)
        except asyncio.TimeoutError:
            dev = None
    if dev is None:
        print("nessuna bilancia riconosciuta. Dispositivi vicini (rssi > -72):")
        for addr, v in sorted(vicini.items(), key=lambda kv: -kv[1]["rssi"]):
            if v["rssi"] > -72:
                print("  %s rssi %s %r servizi=%s" % (addr, v["rssi"], v["nome"], v["servizi"]))
                for d in sorted(v["dati"])[:6]:
                    print("      " + d[:120])
        return
    await ascolta(dev, secondi, scritture)


confermare = False


async def ascolta(indirizzo, secondi, scritture):
    reg = Registro("ascolto")
    print("mi collego a", getattr(indirizzo, "address", indirizzo))
    async with BleakClient(indirizzo, timeout=20) as c:
        print("collegato, mtu", getattr(c, "mtu_size", "?"))
        notif = []
        for s in c.services:
            print("servizio", s.uuid)
            for ch in s.characteristics:
                valore = ""
                if "read" in ch.properties:
                    try:
                        dati = await c.read_gatt_char(ch)
                        valore = " = %s %r" % (hx(dati), bytes(dati).decode("utf-8", "replace"))
                    except Exception as e:
                        valore = " (lettura fallita: %s)" % type(e).__name__
                print("   %s %-28s%s" % (ch.uuid[4:8], ",".join(ch.properties), valore[:90]))
                reg.scrivi(tipo="caratteristica", servizio=s.uuid, uuid=ch.uuid, proprieta=list(ch.properties), valore=valore.strip())
                if "notify" in ch.properties or "indicate" in ch.properties:
                    notif.append(ch)

        scrittura = next((ch for sv in c.services for ch in sv.characteristics if ch.uuid[4:8] == "ffb1"), None)

        async def conferma(tipo):
            p = ac27([0x04, tipo], 0xDF)
            await c.write_gatt_char(scrittura, bytes.fromhex(p), response=True)
            print("%7.3f  >> ffb1  %s  (conferma %02x)" % (time.time() - reg.t0, p, tipo), flush=True)
            reg.scrivi(tipo="scrittura", uuid="ffb1", hex=p)

        def arrivo(ch, dati):
            dati = bytes(dati)
            nota = ""
            if len(dati) == 20 and dati[0] == 0xAC and dati[1] == 0x27:
                tipo = dati[18]
                if tipo == 0xD5:
                    nota = "  peso %.3f kg%s" % ((int.from_bytes(dati[3:6], "big") & 0x3FFFF) / 1000, " BLOCCATO" if dati[2] & 0x80 else "")
                elif tipo == 0xD6:
                    nota = "  FINALE peso %.3f kg impedenza %d ohm" % ((int.from_bytes(dati[8:11], "big") & 0x3FFFF) / 1000, int.from_bytes(dati[4:6], "big"))
                elif tipo == 0xD8:
                    nota = "  MEMORIA %s peso %.3f kg" % (time.strftime("%Y-%m-%d %H:%M", time.localtime(int.from_bytes(dati[3:7], "big"))), (int.from_bytes(dati[8:11], "big") & 0x3FFFF) / 1000)
                if confermare and tipo in (0xD6, 0xD8) and scrittura:
                    asyncio.get_running_loop().create_task(conferma(tipo))
            riga = "%7.3f  %s  %s%s" % (time.time() - reg.t0, ch.uuid[4:8], hx(dati), nota)
            print(riga, flush=True)
            reg.scrivi(tipo="notifica", uuid=ch.uuid[4:8], hex=hx(dati))

        for ch in notif:
            try:
                await c.start_notify(ch, arrivo)
                print("in ascolto su", ch.uuid[4:8])
            except Exception as e:
                print("non riesco ad ascoltare", ch.uuid[4:8], type(e).__name__, e)

        for breve, pacchetti in scritture:
            bersaglio = next((ch for s in c.services for ch in s.characteristics if ch.uuid[4:8] == breve), None)
            if not bersaglio:
                print("caratteristica", breve, "non trovata")
                continue
            for p in pacchetti:
                dati = bytes.fromhex(p)
                senza_risposta = "write-without-response" in bersaglio.properties and "write" not in bersaglio.properties
                await c.write_gatt_char(bersaglio, dati, response=not senza_risposta)
                print("%7.3f  >> %s  %s" % (time.time() - reg.t0, breve, p), flush=True)
                reg.scrivi(tipo="scrittura", uuid=breve, hex=p)
                await asyncio.sleep(0.15)

        fine = time.time() + secondi
        while time.time() < fine and c.is_connected:
            await asyncio.sleep(0.25)
        print("fine ascolto, ancora collegato:", c.is_connected)
    print("registro:", reg.percorso)


def main():
    # la console di Windows non regge tutti i caratteri che una bilancia puo' mandare
    for flusso in (sys.stdout, sys.stderr):
        flusso.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("azione", choices=["scan", "auto", "ascolta"])
    ap.add_argument("arg", nargs="*")
    ap.add_argument("--scrivi", action="append", default=[])
    ap.add_argument("--ac27", help="protocollo AC 27 (Runstar R5 FG2431WB): sesso,eta,altezza (es. m,30,175)")
    ap.add_argument("--runstar", help="manda il saluto della Runstar R5: sesso,eta,altezza (es. m,30,175)")
    a = ap.parse_args()
    scritture = []
    if a.ac27:
        global confermare
        confermare = True
        sesso, eta, altezza = a.ac27.split(",")
        scritture.append(("ffb1", saluto_ac27(sesso.lower(), int(eta), int(altezza))))
    if a.runstar:
        sesso, eta, altezza = a.runstar.split(",")
        scritture.append(("ffb1", saluto_runstar(sesso.lower(), int(eta), int(altezza))))
    for voce in a.scrivi:
        breve, _, elenco = voce.partition("=")
        scritture.append((breve.lower(), [x for x in elenco.split(",") if x]))
    if a.azione == "scan":
        asyncio.run(scan(int(a.arg[0]) if a.arg else 10))
    elif a.azione == "auto":
        asyncio.run(auto(int(a.arg[0]) if a.arg else 90, int(a.arg[1]) if len(a.arg) > 1 else 60, scritture))
    else:
        asyncio.run(ascolta(a.arg[0], int(a.arg[1]) if len(a.arg) > 1 else 60, scritture))


if __name__ == "__main__":
    main()

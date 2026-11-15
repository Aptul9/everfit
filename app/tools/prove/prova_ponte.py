"""Il ponte tra telefono e sentinella (server/ponte.py) con un orologio finto: quando il pallino e' verde o rosso,
e cosa finisce nel registro. Il 28/10/2026 il capo: "devi capire perche' non e' sempre verde".

    python prova_ponte.py
"""
import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "server"))
import ponte  # noqa: E402

ora = [1_000_000.0]
ponte.time.time = lambda: ora[0]
sbagli = []


def controlla(nome, vero, dettaglio=""):
    print(("ok   " if vero else "NO   ") + nome + ("" if vero else "  %r" % (dettaglio,)))
    if not vero:
        sbagli.append(nome)


def registro(fai):
    uscita = io.StringIO()
    with contextlib.redirect_stdout(uscita):
        risultato = fai()
    return risultato, uscita.getvalue()


p = ponte.Ponte()
controlla("appena ripartito il server, la sentinella e' data per presente", p.sentinella()["online"])
ora[0] += ponte.VIVA - 1
controlla("fino a VIVA secondi resta verde", p.sentinella()["online"])
ora[0] += 2
j, scritto = registro(p.sentinella)
controlla("dopo VIVA secondi senza notizie: rosso", not j["online"], j)
controlla("e nel registro c'e' da quanto non si sente", "non si sente da %d s" % (ponte.VIVA + 1) in scritto, scritto)
_, scritto = registro(p.sentinella)
controlla("una riga sola per ogni assenza, anche se il telefono chiede di continuo", scritto == "", scritto)
ora[0] += 100
_, scritto = registro(lambda: p.prendi(0))
controlla("la sentinella torna: nel registro quanto e' durata", "tornata dopo %d s" % (ponte.VIVA + 101) in scritto, scritto)
controlla("e il pallino torna verde", p.sentinella()["online"])
_, scritto = registro(lambda: p.prendi(0))
controlla("finche' si fa sentire, niente nel registro", scritto == "", scritto)

# una pesata chiesta dal telefono, presa e finita: le notizie della sentinella la tengono verde
lavoro = p.chiedi({"sesso": "m"})
preso = p.prendi(0)
controlla("la sentinella prende la richiesta del telefono", preso and preso["id"] == lavoro["id"], preso)
ora[0] += 30
p.riferisci(lavoro["id"], evento={"fase": "cerca"})
ora[0] += 30
controlla("durante la pesata, con le notizie, resta verde", p.sentinella()["online"])
p.riferisci(lavoro["id"], esito={"ok": True, "peso": 61.2})
controlla("l'esito arriva al telefono", p.segui(lavoro["id"], 0, 0)["esito"]["peso"] == 61.2)

# senza sentinella la richiesta viene rifiutata con la spiegazione
ora[0] += ponte.VIVA + 5
try:
    registro(lambda: p.chiedi({}))
    controlla("senza sentinella: richiesta rifiutata", False)
except ponte.Problema as e:
    controlla("senza sentinella: richiesta rifiutata (503) con la spiegazione", e.codice == 503 and "riparte da solo" in e.testo, e.testo)

print("\n%s" % ("TUTTO A POSTO" if not sbagli else "SBAGLIATI: %s" % sbagli))
sys.exit(1 if sbagli else 0)

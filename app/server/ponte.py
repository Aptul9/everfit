"""Ponte tra il telefono e la bilancia.

Il telefono non puo' parlare con la bilancia (Safari non ha il Bluetooth): chiede una pesata al server,
la sentinella accesa sul PC di casa la raccoglie, la fa fare alla bilancia e riferisce passo passo.

    telefono     POST richiesta {profilo}  ->  {id}
                 GET  stato?id=&dopo=N     ->  {eventi dal N-esimo, prossimo, esito}     (aspetta finche' c'e' qualcosa)
                 POST annulla {id}
    sentinella   GET  lavoro               ->  {id, profilo} oppure niente                (aspetta finche' c'e' lavoro)
                 POST notizie {id, evento?, esito?}  ->  {annullata}

Tutto in memoria: una richiesta alla volta, un utente solo. Se il server riparte la pesata in corso si perde.
"""
import threading
import time
import uuid

from cibo import Problema

VIVA = 45           # secondi: oltre, la sentinella e' considerata spenta (si fa sentire almeno ogni 25)
PRESA_ENTRO = 12    # secondi: se nessuno raccoglie la richiesta, il PC non c'e'
SILENZIO = 150      # secondi: senza notizie dalla sentinella la pesata e' persa

# Fino al 27/10/2026 la sentinella stava sul portatile, che ogni notte si addormentava fino a quando lo si apriva: al
# mattino, quando ci si pesa, non rispondeva mai. Dal 27/10 sta sul server, sempre acceso: se non risponde e' un guasto
# (di solito il servizio sta ripartendo, e torna da solo in pochi secondi).
PC_ASSENTE = ("Il PC di casa che collega la bilancia non risponde. Di solito riparte da solo entro un minuto: riprova, "
              "oppure segna il peso a mano. Se sali sulla bilancia adesso, la pesata resta nella sua memoria e la "
              "recupero alla prossima.")


class Ponte:
    def __init__(self):
        self.cv = threading.Condition()
        # l'ultima volta che la sentinella si e' fatta sentire. Appena ripartito il server non lo sa ancora: la si da'
        # per presente, perche' si ricollega in pochi secondi. Altrimenti ogni riavvio del server (una pubblicazione)
        # farebbe vedere il pallino rosso a chi ha l'app aperta proprio in quel momento.
        self.vista = time.time()
        self.lavoro = None
        self.assente = False    # gia' scritto nel registro che la sentinella manca (una riga per ogni assenza)

    def _in_corso(self):
        l = self.lavoro
        return bool(l and l["esito"] is None and l["presa"] and time.time() - l["notizie"] < 20)

    def _si_sente(self):
        """La sentinella si e' fatta sentire adesso. Se era sparita lo si scrive nel registro, con quanto e' durata:
        le richieste della sentinella e del telefono non ci finiscono (sono troppe), e senza questa riga un pallino
        rosso non si potrebbe spiegare dopo."""
        ora = time.time()
        if ora - self.vista >= VIVA:
            print("bilancia: la sentinella e' tornata dopo %d s di silenzio" % (ora - self.vista), flush=True)
        self.vista, self.assente = ora, False
        return ora

    def sentinella(self):
        with self.cv:
            ora = time.time()
            online = ora - self.vista < VIVA
            if not online and not self.assente:
                self.assente = True
                print("bilancia: il telefono la cerca e la sentinella non si sente da %d s" % (ora - self.vista), flush=True)
            return {"online": online, "occupata": self._in_corso()}

    # ---- dal telefono
    def chiedi(self, profilo):
        with self.cv:
            if time.time() - self.vista >= VIVA:
                raise Problema(503, PC_ASSENTE)
            if self._in_corso():
                raise Problema(409, "C'e' gia' una pesata in corso: aspetta che finisca.")
            ora = time.time()
            self.lavoro = {"id": uuid.uuid4().hex[:12], "profilo": profilo if isinstance(profilo, dict) else {},
                           "eventi": [], "esito": None, "presa": False, "annullata": False, "creata": ora, "notizie": ora}
            self.cv.notify_all()
            return {"id": self.lavoro["id"]}

    def segui(self, ident, dopo, attesa):
        fine = time.time() + attesa
        with self.cv:
            while True:
                l = self.lavoro
                if not l or l["id"] != ident:
                    return {"eventi": [], "prossimo": dopo, "esito": {"ok": False, "errore": "Pesata scaduta: riprova."}}
                ora = time.time()
                if l["esito"] is None:
                    if not l["presa"] and ora - l["creata"] > PRESA_ENTRO:
                        l["esito"] = {"ok": False, "errore": PC_ASSENTE}
                    elif l["presa"] and ora - l["notizie"] > SILENZIO:
                        l["esito"] = {"ok": False, "errore": "Il PC ha smesso di rispondere a meta' pesata. Riprova."}
                if len(l["eventi"]) > dopo or l["esito"] is not None:
                    return {"eventi": l["eventi"][dopo:], "prossimo": len(l["eventi"]), "esito": l["esito"]}
                if ora >= fine:
                    return {"eventi": [], "prossimo": dopo, "esito": None}
                self.cv.wait(min(fine - ora, 2))

    def annulla(self, ident):
        with self.cv:
            l = self.lavoro
            if l and l["id"] == ident and l["esito"] is None:
                l["annullata"] = True
                l["esito"] = {"ok": False, "annullata": True, "errore": "Pesata annullata."}
                self.cv.notify_all()
            return {"ok": True}

    # ---- dalla sentinella
    def prendi(self, attesa):
        fine = time.time() + attesa
        with self.cv:
            while True:
                ora = self._si_sente()
                l = self.lavoro
                if l and not l["presa"] and l["esito"] is None:
                    l["presa"] = True
                    l["notizie"] = ora
                    self.cv.notify_all()
                    return {"id": l["id"], "profilo": l["profilo"]}
                if ora >= fine:
                    return None
                self.cv.wait(min(fine - ora, 5))

    def riferisci(self, ident, evento=None, esito=None):
        with self.cv:
            ora = self._si_sente()
            l = self.lavoro
            if not l or l["id"] != ident:
                return {"annullata": True}
            l["notizie"] = ora
            if isinstance(evento, dict) and len(l["eventi"]) < 2000:
                l["eventi"].append({"fase": str(evento.get("fase"))[:20], "kg": evento.get("kg")})
            if isinstance(esito, dict) and l["esito"] is None:
                l["esito"] = esito
            self.cv.notify_all()
            return {"annullata": l["annullata"]}

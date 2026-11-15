"""I piani scritti a mano per le persone che non sono il capo: uno per nome utente.

Li chiama build_plan.py, che scrive un file per ciascuno in server/piani/<nome utente>.json. Il server da' ogni file
solo all'account con quel nome utente, e l'app lo mette sopra al catalogo: profilo, obiettivi, settimana, e in piu'
i cibi, le ricette, i momenti della giornata e le schede che sono solo di quella persona.

    test            una dieta inventata, per provare l'app e le domande del primo avvio

Per aggiungere una persona: una funzione come prova() qui sotto che restituisce il suo piano, e una riga in PIANI.
Un piano pronto per un nome utente che non ha ancora un account compare al capo come "account in attesa".
"""
import json
import os


def _totali(cibi, ricette, pasti):
    t = {"kcal": 0.0, "p": 0.0, "c": 0.0, "f": 0.0}
    for rid in pasti.values():
        for cibo, g, _ in ricette[rid]["ing"]:
            for k in t:
                t[k] += cibi[cibo][k] * g / 100
    return t


def _obiettivo(t):
    return {"kcal": int(round(t["kcal"], -1)), "p": int(round(t["p"])), "c": int(round(t["c"])), "f": int(round(t["f"]))}


def _media(lista):
    return {k: int(round(sum(x[k] for x in lista) / len(lista), -1 if k == "kcal" else 0)) for k in ("kcal", "p", "c", "f")} if lista else None


def _settimana(cibi, ricette, pasti_dei_giorni, allenamento):
    """La settimana con l'obiettivo di ogni giorno: quello che il piano porta, cosi' chi lo segue chiude il conto."""
    giorni = []
    for wd, pasti in enumerate(pasti_dei_giorni):
        giorni.append({"tipo": "train" if wd in allenamento else "rest", "scheda": allenamento.get(wd) if isinstance(allenamento, dict) else None,
                       "pasti": pasti, "ob": _obiettivo(_totali(cibi, ricette, pasti))})
    return giorni


def prova(base_cibi, base_ricette, settimana_tipo):
    """Una dieta inventata, con i piatti del catalogo: serve a provare l'app e le domande del primo avvio."""
    settimana = _settimana(base_cibi, base_ricette, [g["pasti"] for g in settimana_tipo], {0: None, 2: None, 4: None})
    for g, tipo in zip(settimana, settimana_tipo):
        g["tipo"] = tipo["tipo"]
    # Anche la dieta di prova esiste in due forme, cosi' con questo account si vede la domanda che l'app fa a chi ha uno
    # schema fisso con le alternative: nella forma fissa i giorni di palestra ripetono il lunedi', gli altri il martedi'.
    fissa = _settimana(base_cibi, base_ricette, [dict(settimana_tipo[0 if g["tipo"] == "train" else 1]["pasti"]) for g in settimana_tipo],
                       {0: None, 2: None, 4: None})
    for g, tipo in zip(fissa, settimana_tipo):
        g["tipo"] = tipo["tipo"]
    return {
        "profilo": {"nome": "Test", "sesso": "m", "eta": 30, "altezza": 175, "pesoIniziale": 75.0, "pesoObiettivo": 72.0,
                    "dataInizio": "2026-10-10", "lattosio": False, "allena": True, "giorni": [0, 2, 4], "shake": False,
                    "creatina": False, "da": "Admin", "note": "Account di prova: la dieta è inventata."},
        "obiettivi": {"train": _media([g["ob"] for g in settimana if g["tipo"] == "train"]),
                      "rest": _media([g["ob"] for g in settimana if g["tipo"] == "rest"]),
                      "acqua": {"rest": 2600, "train": 3100}, "camminataMin": 30},
        "settimana": settimana, "settimanaFissa": fissa, "puntiCarenti": [],
        "obiettiviFissi": {"train": _media([g["ob"] for g in fissa if g["tipo"] == "train"]),
                           "rest": _media([g["ob"] for g in fissa if g["tipo"] == "rest"])},
        "menu": {
            "testo": "È una dieta inventata, ma te la posso far vedere in due modi, come succede a chi ha uno schema fisso con le alternative.",
            "giro": ["Un menu diverso ogni giorno", "Pranzo e cena cambiano da lunedì a domenica. Tu segui e basta."],
            "fisso": ["Sempre lo stesso schema", "Ogni giorno gli stessi pasti. Le alternative le scegli tu, pasto per pasto, con «Sostituisci»."],
        },
        "guida": [{"id": "prova", "t": "Account di prova", "icona": "info", "p": [
            "Questa dieta è inventata: serve solo a provare l'app.", "I piatti sono quelli del catalogo, con quantità qualunque."]}],
    }


def scrivi(cartella, versione, base_cibi, base_ricette, settimana_tipo, esercizi):
    """Scrive server/piani/<nome utente>.json per ciascuno, dopo aver controllato ricette ed esercizi."""
    piani = {"test": prova(base_cibi, base_ricette, settimana_tipo)}
    for utente, piano in piani.items():
        for scheda in piano.get("schede", {}).values():
            for es in scheda["es"]:
                assert es[0] in esercizi, f"{utente}: esercizio sconosciuto {es[0]}"
        for g in piano["settimana"] + piano.get("settimanaFissa", []):
            for momento, rid in g["pasti"].items():
                ricette = piano.get("ricette", base_ricette)
                assert rid in ricette, f"{utente}: ricetta sconosciuta {rid}"
                momenti = piano.get("momenti")
                assert not momenti or (momento in momenti and ricette[rid]["tipo"] == momenti[momento]["tipo"]), f"{utente}: {rid} non va a {momento}"
        piano["versione"] = versione
        os.makedirs(cartella, exist_ok=True)
        with open(os.path.join(cartella, utente + ".json"), "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(piano, ensure_ascii=False, separators=(",", ":")))

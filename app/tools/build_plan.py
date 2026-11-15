#!/usr/bin/env python3
"""Genera il contenuto dell'app: dieta, schede e guida.

Scrive due file:
    public/data/plan.json     il catalogo, uguale per tutti: cibi, ricette, esercizi, schede e una settimana tipo.
                              Chi entra con un account suo riceve da qui un piano calcolato dall'app sul suo profilo
                              (public/js/personale.js): calorie, quantita', giorni di allenamento, cibi esclusi.
    server/piani/admin.json   il piano scritto a mano per il capo (profilo, obiettivi, settimana, punti carenti,
                              guida): il server lo da' solo al suo account e l'app lo mette sopra al catalogo.

Dopo una modifica:
    python tools/build_plan.py          genera i due file e stampa i totali del giorno
    python tools/build_plan.py --check  stampa solo i totali, senza scrivere
"""
import json
import os
import sys
from datetime import datetime

import persone

QUI = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(QUI, "..", "public", "data", "plan.json")
PIANI = os.path.join(QUI, "..", "server", "piani")   # un file per nome utente: il server lo da' solo a quell'account
OUT_MIO = os.path.join(PIANI, "admin.json")   # il nome utente del capo (FIT_UTENTE; senza, admin)
VIDEO = os.path.join(QUI, "video.json")   # un video di YouTube per esercizio: {"id esercizio": {"yt": "...", ...}}

PROFILO = {
    "nome": "Admin",
    "sesso": "m",
    "eta": 30,          # usata per la composizione corporea: aggiornarla al compleanno, o mettere "nascita": "AAAA-MM-GG"
    "altezza": 175,
    "pesoIniziale": 75.0,
    "dataInizio": "2026-11-01",
    "pesoObiettivo": 72.0,
    "grasso": 18.0,
    "massaMagra": 61.5,
    "metabolismoBasale": 1700,
    # per il giudizio sui prodotti scansionati e per il parere scritto dall'AI
    "lattosio": False,   # True = intollerante: un prodotto con latte e senza la dicitura "senza lattosio" viene segnalato
    "note": "Profilo d'esempio: qui vanno obiettivo, lavoro e allenamento della persona.",
    # per l'assistente: senza, proporrebbe cibi che non mangia
    "preferenze": "Profilo d'esempio: qui vanno cosa mangia e cosa no, come cucina, cosa prende dopo l'allenamento.",
    "allena": True,
    "creatina": True,
}

# Obiettivi d'esempio, per perdere grasso: circa il 17% sotto quello che si consuma, senza scendere sotto il minimo,
# con le proteine sopra 2 g per chilo. A chi non ha un piano scritto a mano l'app li calcola dal profilo (personale.js).
OBIETTIVI = {
    "train": {"kcal": 1900, "p": 150, "c": 200, "f": 55},
    "rest": {"kcal": 1700, "p": 140, "c": 160, "f": 55},
    # millilitri d'acqua al giorno: circa 35 ml per chilo, piu' mezzo litro quando ci si allena (e si prende creatina)
    "acqua": {"rest": 2300, "train": 2800},
    "camminataMin": 30,
}

# Valori per 100 g di alimento a crudo (o cosi' come si compra, se pronto).
# rep = reparto della lista della spesa. pz = peso di un pezzo, quando si conta a pezzi.
CIBI = {
    "riso": {"n": "Riso basmati", "kcal": 351, "p": 8.5, "c": 77.5, "f": 0.9, "rep": "Dispensa"},
    "pasta": {"n": "Pasta", "kcal": 356, "p": 12.5, "c": 72.0, "f": 1.5, "rep": "Dispensa"},
    "patate": {"n": "Patate", "kcal": 77, "p": 2.0, "c": 17.0, "f": 0.1, "rep": "Frutta e verdura"},
    "tortilla": {"n": "Tortillas di grano", "kcal": 310, "p": 8.5, "c": 52.0, "f": 7.0, "rep": "Dispensa",
                 "pz": 40, "pzn": ["tortilla", "tortillas"]},
    "gallette": {"n": "Gallette di riso", "kcal": 385, "p": 8.0, "c": 81.0, "f": 3.0, "rep": "Dispensa",
                 "pz": 9, "pzn": ["galletta", "gallette"]},
    "fette": {"n": "Fette biscottate", "kcal": 410, "p": 12.0, "c": 73.0, "f": 6.5, "rep": "Dispensa",
              "pz": 8, "pzn": ["fetta", "fette"]},
    "pancake": {"n": "Pancake proteici pronti", "kcal": 225, "p": 19.0, "c": 22.0, "f": 6.0, "rep": "Frigo",
                "pz": 40, "pzn": ["pancake", "pancake"], "nota": "Controlla che siano senza lattosio."},
    "barretta": {"n": "Barretta proteica", "kcal": 364, "p": 36.4, "c": 29.1, "f": 12.7, "rep": "Dispensa",
                 "pz": 55, "pzn": ["barretta", "barrette"]},
    # EAN 5900020043832, valori da Open Food Facts: e' una barretta di cereali, non proteica (2,4 g di proteine l'una)
    "barretta_fitness": {"n": "Barretta Nestlé Fitness cacao", "kcal": 330, "p": 11.9, "c": 41.0, "f": 9.4,
                         "rep": "Dispensa", "pz": 20, "pzn": ["barretta", "barrette"]},
    "banana": {"n": "Banana", "kcal": 89, "p": 1.1, "c": 20.5, "f": 0.3, "rep": "Frutta e verdura",
               "pz": 120, "pzn": ["banana", "banane"]},
    "pollo": {"n": "Petto di pollo", "kcal": 108, "p": 23.5, "c": 0.0, "f": 1.5, "rep": "Carne e pesce"},
    "tacchino": {"n": "Fesa di tacchino", "kcal": 106, "p": 24.0, "c": 0.0, "f": 1.1, "rep": "Carne e pesce"},
    "pollo_arrosto": {"n": "Pollo arrosto affettato", "kcal": 110, "p": 21.0, "c": 1.0, "f": 2.5, "rep": "Frigo"},
    "fesa_aff": {"n": "Fesa di tacchino affettata", "kcal": 105, "p": 21.0, "c": 1.0, "f": 2.0, "rep": "Frigo"},
    "hamburger": {"n": "Hamburger di pollo", "kcal": 155, "p": 16.0, "c": 3.0, "f": 9.0, "rep": "Carne e pesce",
                  "pz": 100, "pzn": ["hamburger", "hamburger"]},
    "salmone": {"n": "Filetto di salmone", "kcal": 200, "p": 20.0, "c": 0.0, "f": 13.5, "rep": "Carne e pesce"},
    "tonno": {"n": "Tonno al naturale", "kcal": 105, "p": 24.5, "c": 0.0, "f": 0.8, "rep": "Dispensa",
              "pz": 56, "pzn": ["scatoletta", "scatolette"], "nota": "Scatoletta da 80 g, 56 g sgocciolato."},
    "merluzzo": {"n": "Filetti di merluzzo", "kcal": 75, "p": 17.0, "c": 0.0, "f": 0.6, "rep": "Surgelati"},
    "gamberi": {"n": "Gamberi sgusciati", "kcal": 80, "p": 17.5, "c": 0.5, "f": 0.9, "rep": "Surgelati"},
    "uova": {"n": "Uova", "kcal": 140, "p": 12.5, "c": 0.7, "f": 9.7, "rep": "Frigo",
             "pz": 55, "pzn": ["uovo", "uova"]},
    "mozzarella": {"n": "Mozzarella senza lattosio", "kcal": 245, "p": 18.0, "c": 0.7, "f": 19.0, "rep": "Frigo"},
    "grana": {"n": "Grana", "kcal": 395, "p": 33.0, "c": 0.0, "f": 29.0, "rep": "Frigo",
              "nota": "Stagionato, naturalmente privo di lattosio."},
    "fiocchi": {"n": "Fiocchi di latte senza lattosio", "kcal": 95, "p": 12.0, "c": 2.5, "f": 4.2, "rep": "Frigo"},
    "vellutata": {"n": "Vellutata di zucca e carote", "kcal": 46, "p": 0.9, "c": 6.0, "f": 1.9, "rep": "Frigo",
                  "nota": "Senza panna, meno di 55 kcal per 100 g."},
    "pomodorini": {"n": "Pomodorini", "kcal": 20, "p": 1.0, "c": 3.5, "f": 0.2, "rep": "Frutta e verdura"},
    "pomodori": {"n": "Pomodori da insalata", "kcal": 19, "p": 0.9, "c": 3.5, "f": 0.2, "rep": "Frutta e verdura"},
    "carote": {"n": "Carote a rondelle al vapore", "kcal": 35, "p": 0.8, "c": 6.8, "f": 0.2, "rep": "Frigo"},
    "spinaci": {"n": "Spinaci", "kcal": 28, "p": 3.0, "c": 1.5, "f": 0.6, "rep": "Surgelati"},
    "piselli": {"n": "Piselli", "kcal": 80, "p": 5.5, "c": 11.0, "f": 0.5, "rep": "Surgelati"},
    "lenticchie": {"n": "Lenticchie in scatola", "kcal": 92, "p": 7.0, "c": 13.0, "f": 0.5, "rep": "Dispensa",
                   "nota": "Peso sgocciolato."},
    "fagioli": {"n": "Fagioli in scatola", "kcal": 100, "p": 7.0, "c": 14.0, "f": 0.6, "rep": "Dispensa",
                "nota": "Peso sgocciolato."},
    "noci": {"n": "Noci sgusciate", "kcal": 654, "p": 15.2, "c": 7.0, "f": 65.2, "rep": "Dispensa"},
    "olio": {"n": "Olio extravergine", "kcal": 899, "p": 0.0, "c": 0.0, "f": 99.9, "rep": "Dispensa",
             "pz": 5, "pzn": ["cucchiaino", "cucchiaini"]},
    "whey": {"n": "Proteine in polvere", "kcal": 390, "p": 78.0, "c": 6.5, "f": 6.0, "rep": "Integratori",
             "pz": 30, "pzn": ["misurino", "misurini"]},
}

CIBI["caffe"] = {"n": "Caffè", "kcal": 9, "p": 0.1, "c": 1.7, "f": 0.2, "rep": "Dispensa",
                 "pz": 30, "pzn": ["tazzina", "tazzine"], "spesa": False}

# Per chi dice "questo non lo mangio": i cibi del catalogo divisi per gruppo. Formaggi e latte del catalogo sono
# gia' senza lattosio, quindi l'intolleranza al lattosio non toglie niente; "latticini" e' per chi non li mangia affatto.
GRUPPI = {
    "pesce": {"n": "Pesce", "cibi": ["salmone", "tonno", "merluzzo", "gamberi"]},
    "uova": {"n": "Uova", "cibi": ["uova", "pancake"]},
    "latticini": {"n": "Latticini", "cibi": ["mozzarella", "grana", "fiocchi"]},
    "legumi": {"n": "Legumi", "cibi": ["lenticchie", "fagioli", "piselli"]},
    "glutine": {"n": "Glutine", "cibi": ["pasta", "tortilla", "fette", "pancake", "barretta", "barretta_fitness"]},
}

CUOCIRISO = "Cuociriso"
FRIGGITRICE = "Friggitrice ad aria"
FREDDO = "Senza cottura"

# ing = [cibo, grammi a riposo, grammi nei giorni di palestra]
RICETTE = {
    # ---- colazione
    # Dal 10/10/2026 la colazione di tutti i giorni e' la barretta Nestle' Fitness che il capo mangia davvero
    # (66 kcal, 2,4 g di proteine): le calorie e le proteine che mancano rispetto a una barretta proteica vera
    # (circa 240 kcal e 19 g) stanno in pranzo e cena, che per questo sono piu' abbondanti.
    "col-fitness": {
        # "personale": e' l'abitudine di una persona sola, non una colazione da proporre agli altri
        "n": "Barretta Fitness", "tipo": "colazione", "img": "barretta", "come": FREDDO, "min": 1, "personale": True,
        "ing": [["barretta_fitness", 20, 20]],
        "passi": ["La barretta, come fai di solito.",
                  "È una colazione leggera: per questo pranzo e cena sono un po' più abbondanti.",
                  "Nei giorni senza palestra sciogli qui la creatina in un bicchiere d'acqua."],
        "nota": "Di proteine ne ha poche, 2,4 grammi: non contarla come una barretta proteica.",
    },
    # senza glutine, uova, latticini, pesce e legumi: la colazione che resta a chi ha escluso tutto il resto
    "col-gallette": {
        "n": "Gallette, fesa di tacchino e banana", "tipo": "colazione", "img": "gallette", "come": FREDDO, "min": 2,
        "ing": [["gallette", 36, 36], ["fesa_aff", 60, 60], ["banana", 120, 120]],
        "passi": ["Gallette con la fesa di tacchino sopra.", "La banana a parte, con il caffè o il tè."],
    },
    # il caffe' della colazione ha la sua spunta: c'e' chi prende solo la barretta e chi tutti e due
    "caffe": {
        "n": "Caffè", "tipo": "caffe", "img": "caffe", "come": FREDDO, "min": 1,
        "ing": [["caffe", 30, 30]],
        "passi": ["Un espresso, amaro o con il dolcificante.",
                  "Con lo zucchero sono circa 20 kcal in più a bustina: se lo metti, segnalo nel diario."],
    },
    "col-barretta": {
        "n": "Barretta proteica e banana", "tipo": "colazione", "img": "barretta", "come": FREDDO, "min": 1,
        "ing": [["barretta", 55, 55], ["banana", 120, 120]],
        "passi": ["Barretta, banana e caffè.",
                  "Nei giorni senza palestra sciogli qui la creatina in un bicchiere d'acqua."],
    },
    "col-pancake": {
        "n": "Pancake proteici e banana", "tipo": "colazione", "img": "pancake", "come": FREDDO, "min": 2,
        "ing": [["pancake", 80, 80], ["banana", 120, 120]],
        "passi": ["Scalda i pancake 20 secondi al microonde.", "Banana a rondelle sopra."],
    },
    # ---- pasti principali
    "riso-pollo-vellutata": {
        "n": "Riso, pollo e vellutata di zucca", "tipo": "pasto", "img": "riso-pollo-vellutata",
        "come": CUOCIRISO, "min": 5,
        "ing": [["riso", 75, 85], ["pollo", 190, 190], ["vellutata", 250, 250], ["pomodorini", 100, 100],
                ["olio", 5, 5]],
        "passi": ["Taglia il pollo a cubetti di 2 cm.",
                  "Nel cuociriso: riso sciacquato, pollo, vellutata e mezzo bicchiere d'acqua. Sale e pepe.",
                  "Pomodorini interi sopra, poi avvia il programma riso.",
                  "A fine cottura mescola e aggiungi l'olio a crudo."],
        "nota": "La vellutata fa da condimento: il riso viene cremoso, quasi un risotto.",
    },
    "riso-pollo-carote": {
        "n": "Riso, pollo, carote e pomodorini", "tipo": "pasto", "img": "riso-pollo-carote",
        "come": CUOCIRISO, "min": 5,
        "ing": [["riso", 75, 85], ["pollo", 190, 190], ["carote", 150, 150], ["pomodorini", 100, 100],
                ["grana", 15, 15], ["olio", 5, 5]],
        "passi": ["Taglia il pollo a cubetti di 2 cm.",
                  "Nel cuociriso: riso sciacquato, acqua (una volta e mezza il riso), pollo, carote e pomodorini.",
                  "Avvia il programma riso.",
                  "A fine cottura olio a crudo e grana grattugiato."],
    },
    "riso-pollo-piselli": {
        "n": "Riso, pollo, vellutata e piselli", "tipo": "pasto", "img": "riso-pollo-bowl",
        "come": CUOCIRISO, "min": 5,
        "ing": [["riso", 75, 85], ["pollo", 190, 190], ["vellutata", 200, 200], ["piselli", 80, 80],
                ["olio", 5, 5]],
        "passi": ["Taglia il pollo a cubetti di 2 cm.",
                  "Nel cuociriso: riso sciacquato, pollo, vellutata, piselli surgelati e mezzo bicchiere d'acqua.",
                  "Avvia il programma riso.",
                  "A fine cottura mescola e aggiungi l'olio a crudo."],
    },
    "riso-tacchino-piselli": {
        "n": "Riso, tacchino, piselli e pomodorini", "tipo": "pasto", "img": "riso-piselli",
        "come": CUOCIRISO, "min": 5,
        "ing": [["riso", 75, 85], ["tacchino", 190, 190], ["piselli", 120, 120], ["pomodorini", 100, 100],
                ["grana", 10, 10], ["olio", 5, 5]],
        "passi": ["Taglia il tacchino a cubetti di 2 cm.",
                  "Nel cuociriso: riso sciacquato, acqua (una volta e mezza il riso), tacchino, piselli e pomodorini.",
                  "Avvia il programma riso.",
                  "A fine cottura olio a crudo e grana grattugiato."],
    },
    "riso-tacchino-vellutata": {
        "n": "Riso, tacchino e vellutata di zucca", "tipo": "pasto", "img": "vellutata",
        "come": CUOCIRISO, "min": 5,
        "ing": [["riso", 75, 85], ["tacchino", 190, 190], ["vellutata", 250, 250], ["pomodorini", 100, 100],
                ["olio", 5, 5]],
        "passi": ["Taglia il tacchino a cubetti di 2 cm.",
                  "Nel cuociriso: riso sciacquato, tacchino, vellutata e mezzo bicchiere d'acqua. Sale e pepe.",
                  "Pomodorini interi sopra, poi avvia il programma riso.",
                  "A fine cottura mescola e aggiungi l'olio a crudo."],
    },
    "riso-lenticchie": {
        "n": "Riso, lenticchie, tacchino e pomodorini", "tipo": "pasto", "img": "riso-lenticchie",
        "come": CUOCIRISO, "min": 5,
        "ing": [["riso", 75, 85], ["tacchino", 170, 170], ["lenticchie", 120, 120], ["pomodorini", 100, 100],
                ["olio", 10, 10]],
        "passi": ["Taglia il tacchino a cubetti e sciacqua le lenticchie.",
                  "Nel cuociriso: riso sciacquato, acqua (una volta e mezza il riso), tacchino, lenticchie e pomodorini.",
                  "Avvia il programma riso.",
                  "A fine cottura olio a crudo."],
    },
    "riso-gamberi": {
        "n": "Riso, gamberi, piselli e pomodorini", "tipo": "pasto", "img": "riso-gamberi",
        "come": CUOCIRISO, "min": 3,
        "ing": [["riso", 80, 90], ["gamberi", 250, 250], ["piselli", 100, 100], ["pomodorini", 100, 100],
                ["olio", 5, 5]],
        "passi": ["Nel cuociriso: riso sciacquato, acqua (una volta e mezza il riso), piselli e pomodorini.",
                  "Avvia. Dopo 10 minuti aggiungi i gamberi ancora surgelati e richiudi.",
                  "A fine cottura olio a crudo e, se ti va, limone."],
    },
    "salmone-riso": {
        "n": "Salmone, riso e spinaci", "tipo": "pasto", "img": "salmone-riso",
        "come": FRIGGITRICE, "min": 5,
        "ing": [["salmone", 180, 180], ["riso", 65, 75], ["spinaci", 150, 150], ["olio", 5, 5]],
        "passi": ["Riso e spinaci surgelati nel cuociriso con l'acqua (una volta e mezza il riso).",
                  "Salmone in friggitrice: 180° per 9-10 minuti con la pelle sotto. Sale e limone.",
                  "Impiatta e aggiungi l'olio a crudo sul riso."],
        "nota": "Senza friggitrice: salmone nel cestello a vapore del cuociriso, sopra il riso.",
    },
    "salmone-patate": {
        "n": "Salmone, patate e pomodori", "tipo": "pasto", "img": "salmone-patate",
        "come": FRIGGITRICE, "min": 8,
        "ing": [["salmone", 180, 180], ["patate", 270, 320], ["pomodori", 150, 150], ["olio", 5, 5]],
        "passi": ["Patate a spicchi con l'olio e il sale: 200° per 10 minuti.",
                  "Aggiungi il salmone nel cestello e prosegui a 180° per altri 9-10 minuti.",
                  "Pomodori a fette con sale e aceto balsamico."],
    },
    "hamburger-patate": {
        "n": "Hamburger di pollo, patate e pomodori", "tipo": "pasto", "img": "hamburger-patate",
        "come": FRIGGITRICE, "min": 8,
        "ing": [["hamburger", 300, 300], ["patate", 200, 200], ["pomodori", 150, 150], ["olio", 5, 5]],
        "passi": ["Patate a spicchi con l'olio e il sale: 200° per 10 minuti.",
                  "Aggiungi gli hamburger e prosegui a 190° per 10-12 minuti, girandoli a metà.",
                  "Pomodori a fette con sale e aceto balsamico."],
    },
    "merluzzo-patate": {
        "n": "Merluzzo, patate e spinaci", "tipo": "pasto", "img": "merluzzo-patate",
        "come": FRIGGITRICE, "min": 8,
        "ing": [["merluzzo", 310, 310], ["patate", 350, 400], ["spinaci", 150, 150], ["olio", 10, 10]],
        "passi": ["Patate a spicchi con metà dell'olio e il sale: 200° per 10 minuti.",
                  "Aggiungi i filetti di merluzzo, anche surgelati, e prosegui a 180° per 10-12 minuti.",
                  "Spinaci 5 minuti al microonde. Il resto dell'olio a crudo e limone su tutto."],
    },
    "tortillas-pollo": {
        "n": "Tortillas con pollo arrosto e mozzarella", "tipo": "pasto", "img": "tortillas-pollo",
        "come": FREDDO, "min": 5,
        "ing": [["tortilla", 80, 120], ["pollo_arrosto", 190, 190], ["mozzarella", 40, 40],
                ["pomodori", 150, 150], ["olio", 5, 5]],
        "passi": ["Scalda le tortillas 20 secondi al microonde.",
                  "Farcisci con pollo arrosto, pomodoro a fette e mozzarella a pezzetti.",
                  "Olio, glassa di aceto balsamico e arrotola."],
    },
    "burrito": {
        "n": "Burrito di pollo e fagioli", "tipo": "pasto", "img": "burrito",
        "come": FREDDO, "min": 6,
        "ing": [["tortilla", 80, 80], ["pollo_arrosto", 150, 150], ["fagioli", 100, 100],
                ["pomodori", 100, 100], ["mozzarella", 50, 50]],
        "passi": ["Scola e sciacqua i fagioli, poi un minuto al microonde.",
                  "Farcisci le tortillas con pollo, fagioli, pomodoro a cubetti e mozzarella.",
                  "Arrotola. Se le vuoi croccanti: 3 minuti in friggitrice a 200°."],
    },
    "pasta-tonno": {
        "n": "Pasta, tonno e pomodorini", "tipo": "pasto", "img": "pasta-tonno",
        "come": "Pentola", "min": 5,
        "ing": [["pasta", 95, 105], ["tonno", 168, 168], ["pomodorini", 150, 150], ["olio", 10, 10]],
        "passi": ["Cuoci la pasta.",
                  "In una ciotola: tonno sgocciolato, pomodorini tagliati a metà, olio e sale.",
                  "Scola la pasta e mescola tutto."],
    },
    "tortilla-uova": {
        "n": "Tortillas con uova strapazzate e spinaci", "tipo": "pasto", "img": "tortilla-uova",
        "come": "Padella", "min": 7,
        "ing": [["tortilla", 80, 120], ["uova", 165, 165], ["fesa_aff", 130, 130], ["spinaci", 150, 150]],
        "passi": ["Spinaci 4 minuti al microonde, poi strizzali.",
                  "Strapazza le uova in padella antiaderente con gli spinaci, senza olio.",
                  "Farcisci le tortillas calde con uova e fesa di tacchino."],
    },
    "cena-libera": {
        # la foto non sta nell'app: si vede di rado, la prende da Pexels quando serve (come quelle di tools/persone.py)
        "n": "Pasto libero", "tipo": "pasto", "img": None, "come": "Fuori o a casa", "min": 0, "libero": True,
        "foto": "https://images.pexels.com/photos/315755/pexels-photo-315755.jpeg?auto=compress&cs=tinysrgb&w=800&h=600&fit=crop",
        "stima": {"kcal": 900, "p": 35, "c": 100, "f": 35},
        "ing": [],
        "passi": ["Una volta a settimana mangia quello che vuoi: pizza, sushi, quello che capita.",
                  "Mangia fino a essere sazio, non fino a scoppiare.",
                  "Il giorno dopo si riprende il piano normale, senza compensare."],
    },
    # ---- merende
    "pre-allenamento": {
        "n": "Banana, gallette e fesa di tacchino", "tipo": "merenda", "img": "banana", "come": FREDDO, "min": 2,
        "ing": [["banana", 120, 120], ["gallette", 18, 18], ["fesa_aff", 60, 60]],
        "passi": ["Un'ora e mezza prima di allenarti.", "Gallette con la fesa sopra, banana a parte."],
    },
    "uova-gallette": {
        "n": "Uova sode e gallette", "tipo": "merenda", "img": "uova-sode", "come": "Pentolino", "min": 2,
        "ing": [["uova", 110, 110], ["gallette", 18, 27]],
        "passi": ["Uova in acqua bollente per 9 minuti. Puoi farne 6 e tenerle in frigo fino a 4 giorni.",
                  "Sale, pepe e gallette."],
    },
    "fiocchi-fette": {
        "n": "Fiocchi di latte e fette biscottate", "tipo": "merenda", "img": "fiocchi-latte", "come": FREDDO,
        "min": 1,
        "ing": [["fiocchi", 150, 150], ["fette", 20, 20]],
        "passi": ["Fiocchi di latte spalmati sulle fette biscottate, con sale e pepe."],
    },
    "gallette-fesa": {
        "n": "Gallette e fesa di tacchino", "tipo": "merenda", "img": "gallette", "come": FREDDO, "min": 1,
        "ing": [["gallette", 27, 36], ["fesa_aff", 120, 120]],
        "passi": ["Gallette con la fesa sopra."],
    },
    # ---- dopo l'allenamento e dopo cena
    "shake": {
        "n": "Shake al caffe' con creatina", "tipo": "post", "img": "shake", "come": FREDDO, "min": 1,
        "ing": [["whey", 0, 30]],
        "passi": ["Un misurino di proteine insapore sciolto nel caffe', con il dolcificante.",
                  "Aggiungi un misurino di creatina e bevilo appena finito l'allenamento.",
                  "Ti alleni di sera: se poi fai fatica a dormire, fallo con il decaffeinato.",
                  "Se le proteine ti danno fastidio alla pancia, passa a quelle isolate: hanno pochissimo lattosio."],
    },
    "noci": {
        "n": "Noci", "tipo": "sera", "img": "noci", "come": FREDDO, "min": 0,
        "ing": [["noci", 20, 20]],
        "passi": ["Quattro noci intere, circa 20 g di gherigli.",
                  "Sono i grassi buoni che ti mancano usando poco olio: non saltarle."],
    },
}

MOMENTI = {
    "colazione": {"n": "Colazione", "ora": {"rest": "08:30", "train": "08:30"}, "tipo": "colazione"},
    # "con": fa parte della colazione; nell'app sta sotto lo stesso titolo ma si spunta per conto suo
    "caffe": {"n": "Colazione", "ora": {"rest": "08:30", "train": "08:30"}, "tipo": "caffe", "con": "colazione"},
    "pranzo": {"n": "Pranzo", "ora": {"rest": "13:00", "train": "13:00"}, "tipo": "pasto"},
    "merenda": {"n": "Merenda", "ora": {"rest": "17:00", "train": "17:30"}, "tipo": "merenda"},
    "post": {"n": "Dopo l'allenamento", "ora": {"rest": None, "train": "20:30"}, "tipo": "post"},
    "cena": {"n": "Cena", "ora": {"rest": "20:00", "train": "21:15"}, "tipo": "pasto"},
    "sera": {"n": "Dopo cena", "ora": {"rest": "21:30", "train": "22:00"}, "tipo": "sera"},
}

GIORNI = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]

# La settimana del capo. Piu' sotto, da questa, nasce la settimana tipo del catalogo (colazione normale, senza caffe' a parte).

# indice 0 = lunedi'
SETTIMANA = [
    {"tipo": "train", "scheda": "A", "pasti": {"colazione": "col-fitness", "pranzo": "riso-pollo-vellutata",
     "merenda": "pre-allenamento", "post": "shake", "cena": "salmone-riso", "sera": "noci"}},
    {"tipo": "rest", "scheda": None, "pasti": {"colazione": "col-fitness", "pranzo": "tortillas-pollo",
     "merenda": "uova-gallette", "cena": "riso-tacchino-piselli", "sera": "noci"}},
    {"tipo": "train", "scheda": "B", "pasti": {"colazione": "col-fitness", "pranzo": "riso-pollo-carote",
     "merenda": "pre-allenamento", "post": "shake", "cena": "hamburger-patate", "sera": "noci"}},
    {"tipo": "rest", "scheda": None, "pasti": {"colazione": "col-fitness", "pranzo": "riso-lenticchie",
     "merenda": "fiocchi-fette", "cena": "merluzzo-patate", "sera": "noci"}},
    {"tipo": "train", "scheda": "C", "pasti": {"colazione": "col-fitness", "pranzo": "riso-pollo-piselli",
     "merenda": "pre-allenamento", "post": "shake", "cena": "burrito", "sera": "noci"}},
    {"tipo": "rest", "scheda": None, "pasti": {"colazione": "col-fitness", "pranzo": "pasta-tonno",
     "merenda": "uova-gallette", "cena": "riso-gamberi", "sera": "noci"}},
    {"tipo": "rest", "scheda": None, "pasti": {"colazione": "col-fitness", "pranzo": "salmone-patate",
     "merenda": "gallette-fesa", "cena": "tortilla-uova", "sera": "noci"}},
]

# ---- diario: quello che si mangia fuori dal piano
# Piatti e bevande fuori casa. Valori MEDI per un pezzo o una porzione: sono stime, servono a non lasciare il buco.
# (id, nome, gruppo, kcal, proteine, carboidrati, grassi, unita' al singolare, al plurale)
for _giorno in SETTIMANA:
    _giorno["pasti"] = dict([("colazione", _giorno["pasti"]["colazione"]), ("caffe", "caffe")]
                            + [(k, v) for k, v in _giorno["pasti"].items() if k != "colazione"])

# La settimana tipo per gli altri account: stessi pranzi e cene, colazione vera al posto di barretta e caffe'.
# L'app la adatta al profilo: sposta i giorni di palestra, toglie i cibi esclusi e ricalcola le quantita'.
SETTIMANA_TIPO = [
    {"tipo": g["tipo"], "pasti": dict({k: v for k, v in g["pasti"].items() if k not in ("caffe", "post")},
                                      colazione="col-pancake" if i % 2 == 0 else "col-barretta")}
    for i, g in enumerate(SETTIMANA)
]

FUORI = [
    ("pizza-margherita", "Pizza margherita", "Pizzeria", 830, 33, 112, 26, "pizza", "pizze"),
    ("pizza-marinara", "Pizza marinara", "Pizzeria", 660, 18, 110, 15, "pizza", "pizze"),
    ("pizza-diavola", "Pizza diavola o al salame", "Pizzeria", 980, 40, 112, 40, "pizza", "pizze"),
    ("pizza-cotto-funghi", "Pizza prosciutto e funghi", "Pizzeria", 900, 42, 113, 30, "pizza", "pizze"),
    ("pizza-capricciosa", "Pizza capricciosa", "Pizzeria", 950, 43, 114, 34, "pizza", "pizze"),
    ("pizza-4-formaggi", "Pizza quattro formaggi", "Pizzeria", 1050, 46, 110, 46, "pizza", "pizze"),
    ("pizza-bufala", "Pizza con bufala", "Pizzeria", 950, 38, 112, 36, "pizza", "pizze"),
    ("pizza-verdure", "Pizza con verdure", "Pizzeria", 850, 31, 115, 28, "pizza", "pizze"),
    ("pizza-tonno", "Pizza tonno e cipolla", "Pizzeria", 900, 45, 113, 28, "pizza", "pizze"),
    ("pizza-wurstel", "Pizza würstel e patatine", "Pizzeria", 1100, 38, 130, 46, "pizza", "pizze"),
    ("calzone", "Calzone", "Pizzeria", 1000, 45, 115, 38, "calzone", "calzoni"),
    ("pizza-trancio", "Pizza al trancio", "Pizzeria", 520, 20, 62, 20, "trancio", "tranci"),
    ("patatine-fritte", "Patatine fritte", "Pizzeria", 450, 5, 55, 23, "porzione", "porzioni"),
    ("suppli", "Supplì", "Pizzeria", 230, 7, 28, 10, "supplì", "supplì"),
    ("arancino", "Arancino", "Pizzeria", 400, 10, 50, 17, "arancino", "arancini"),

    ("pasta-pomodoro", "Pasta al pomodoro", "Ristorante", 480, 15, 82, 9, "piatto", "piatti"),
    ("pasta-ragu", "Pasta al ragù", "Ristorante", 620, 27, 80, 20, "piatto", "piatti"),
    ("carbonara", "Carbonara", "Ristorante", 750, 30, 80, 33, "piatto", "piatti"),
    ("amatriciana", "Amatriciana", "Ristorante", 680, 24, 80, 27, "piatto", "piatti"),
    ("pasta-pesto", "Pasta al pesto", "Ristorante", 650, 18, 78, 29, "piatto", "piatti"),
    ("pasta-scoglio", "Pasta allo scoglio", "Ristorante", 560, 28, 80, 12, "piatto", "piatti"),
    ("lasagne", "Lasagne", "Ristorante", 560, 27, 44, 30, "porzione", "porzioni"),
    ("risotto", "Risotto", "Ristorante", 550, 13, 85, 17, "piatto", "piatti"),
    ("gnocchi", "Gnocchi al pomodoro", "Ristorante", 520, 14, 90, 11, "piatto", "piatti"),
    ("pollo-griglia", "Petto di pollo alla griglia", "Ristorante", 260, 50, 0, 6, "porzione", "porzioni"),
    ("tagliata", "Tagliata o bistecca di manzo", "Ristorante", 420, 52, 0, 23, "porzione", "porzioni"),
    ("cotoletta", "Cotoletta alla milanese", "Ristorante", 550, 35, 25, 34, "cotoletta", "cotolette"),
    ("grigliata-carne", "Grigliata mista di carne", "Ristorante", 700, 60, 0, 50, "porzione", "porzioni"),
    ("pesce-griglia", "Pesce alla griglia", "Ristorante", 280, 40, 0, 13, "porzione", "porzioni"),
    ("frittura-pesce", "Frittura di pesce", "Ristorante", 600, 30, 35, 38, "porzione", "porzioni"),
    ("insalatona", "Insalatona con pollo o tonno", "Ristorante", 420, 32, 15, 26, "insalatona", "insalatone"),
    ("patate-forno", "Patate al forno di contorno", "Ristorante", 250, 4, 35, 10, "porzione", "porzioni"),
    ("verdure-grigliate", "Verdure grigliate di contorno", "Ristorante", 120, 3, 10, 7, "porzione", "porzioni"),
    ("tagliere", "Tagliere di salumi e formaggi", "Ristorante", 480, 26, 4, 40, "porzione", "porzioni"),
    ("bruschetta", "Bruschetta al pomodoro", "Ristorante", 110, 3, 15, 4, "bruschetta", "bruschette"),
    ("pane-fetta", "Pane del cestino", "Ristorante", 80, 2.5, 16, 0.5, "fetta", "fette"),

    ("hamburger-patatine", "Hamburger con patatine", "Fast food", 1100, 42, 100, 58, "menu", "menu"),
    ("hamburger-panino", "Hamburger, solo il panino", "Fast food", 600, 32, 45, 32, "panino", "panini"),
    ("big-mac", "Big Mac", "Fast food", 510, 26, 42, 26, "panino", "panini"),
    ("crispy-mcbacon", "Crispy McBacon", "Fast food", 520, 30, 33, 29, "panino", "panini"),
    ("mcchicken", "McChicken", "Fast food", 430, 20, 40, 21, "panino", "panini"),
    ("cheeseburger", "Cheeseburger", "Fast food", 300, 16, 31, 12, "panino", "panini"),
    ("nuggets", "Nuggets di pollo", "Fast food", 43, 2.6, 2.7, 2.2, "pezzo", "pezzi"),
    ("patatine-medie", "Patatine medie del fast food", "Fast food", 330, 3.5, 42, 16, "porzione", "porzioni"),
    ("kebab", "Kebab, panino o piadina", "Fast food", 750, 38, 70, 34, "kebab", "kebab"),
    ("hot-dog", "Hot dog", "Fast food", 350, 12, 30, 20, "hot dog", "hot dog"),
    ("pollo-fritto", "Pollo fritto", "Fast food", 220, 15, 8, 14, "pezzo", "pezzi"),
    ("burrito-fuori", "Burrito al messicano", "Fast food", 800, 35, 90, 30, "burrito", "burrito"),
    ("gelato-fast", "Gelato del fast food", "Fast food", 330, 7, 50, 11, "coppa", "coppe"),

    ("nigiri", "Nigiri", "Sushi e poke", 50, 2.6, 7, 1.2, "pezzo", "pezzi"),
    ("uramaki", "Uramaki o roll", "Sushi e poke", 42, 1.5, 6, 1.3, "pezzo", "pezzi"),
    ("hosomaki", "Hosomaki", "Sushi e poke", 23, 0.8, 4, 0.3, "pezzo", "pezzi"),
    ("sashimi", "Sashimi di salmone", "Sushi e poke", 25, 2.4, 0, 1.6, "fetta", "fette"),
    ("tempura", "Tempura di gamberi", "Sushi e poke", 60, 3, 5, 3.5, "pezzo", "pezzi"),
    ("gyoza", "Ravioli o gyoza", "Sushi e poke", 45, 2, 5, 2, "pezzo", "pezzi"),
    ("involtino", "Involtino primavera", "Sushi e poke", 130, 3, 15, 6, "involtino", "involtini"),
    ("riso-cantonese", "Riso alla cantonese", "Sushi e poke", 450, 12, 65, 15, "porzione", "porzioni"),
    ("spaghetti-saltati", "Spaghetti di soia o udon saltati", "Sushi e poke", 480, 15, 70, 15, "porzione", "porzioni"),
    ("edamame", "Edamame", "Sushi e poke", 120, 11, 9, 5, "porzione", "porzioni"),
    ("poke", "Poke bowl", "Sushi e poke", 650, 32, 75, 22, "bowl", "bowl"),
    ("ayce", "All you can eat, la serata intera", "Sushi e poke", 1400, 55, 170, 50, "cena", "cene"),

    ("piadina-crudo", "Piadina crudo e formaggio", "Bar e panini", 620, 27, 55, 31, "piadina", "piadine"),
    ("panino-bar", "Panino con affettato", "Bar e panini", 450, 22, 45, 19, "panino", "panini"),
    ("tramezzino", "Tramezzino", "Bar e panini", 300, 11, 28, 16, "tramezzino", "tramezzini"),
    ("toast", "Toast prosciutto e formaggio", "Bar e panini", 320, 17, 28, 15, "toast", "toast"),
    ("focaccia", "Focaccia o pizzetta", "Bar e panini", 330, 9, 45, 12, "pezzo", "pezzi"),
    ("cornetto", "Cornetto vuoto", "Bar e panini", 230, 5, 27, 11, "cornetto", "cornetti"),
    ("cornetto-crema", "Cornetto alla crema o al cioccolato", "Bar e panini", 320, 6, 38, 16, "cornetto", "cornetti"),
    ("cappuccino", "Cappuccino", "Bar e panini", 80, 4, 6, 4, "tazza", "tazze"),
    ("caffe-zucchero", "Caffè con una bustina di zucchero", "Bar e panini", 22, 0, 5, 0, "caffè", "caffè"),
    ("spremuta", "Spremuta d'arancia", "Bar e panini", 90, 1.5, 20, 0, "bicchiere", "bicchieri"),

    ("gelato", "Gelato, coppetta o cono", "Dolci e sfizi", 260, 5, 32, 12, "gelato", "gelati"),
    ("tiramisu", "Tiramisù", "Dolci e sfizi", 450, 8, 40, 28, "porzione", "porzioni"),
    ("torta", "Fetta di torta", "Dolci e sfizi", 380, 6, 48, 18, "fetta", "fette"),
    ("cioccolato", "Cioccolato fondente", "Dolci e sfizi", 55, 0.8, 4.5, 3.8, "quadretto", "quadretti"),
    ("biscotto", "Biscotti", "Dolci e sfizi", 45, 0.7, 6.5, 1.8, "biscotto", "biscotti"),
    ("patatine-sacchetto", "Patatine in sacchetto piccolo", "Dolci e sfizi", 135, 1.6, 13, 8.5, "sacchetto", "sacchetti"),

    ("birra-media", "Birra media", "Da bere", 170, 1.5, 14, 0, "birra", "birre"),
    ("birra-piccola", "Birra piccola", "Da bere", 85, 0.7, 7, 0, "birra", "birre"),
    ("vino", "Calice di vino", "Da bere", 90, 0, 1, 0, "calice", "calici"),
    ("spritz", "Spritz", "Da bere", 140, 0, 12, 0, "spritz", "spritz"),
    ("cocktail", "Cocktail", "Da bere", 200, 0, 18, 0, "cocktail", "cocktail"),
    ("amaro", "Amaro o digestivo", "Da bere", 100, 0, 8, 0, "bicchierino", "bicchierini"),
    ("bibita", "Bibita zuccherata in lattina", "Da bere", 139, 0, 35, 0, "lattina", "lattine"),
    ("succo", "Succo di frutta", "Da bere", 95, 0.5, 22, 0, "bicchiere", "bicchieri"),
]

# Cibi di tutti i giorni che non sono nel piano: valori per 100 g, GIA' COTTI o pronti da mangiare.
# (id, nome, kcal, proteine, carboidrati, grassi, grammi di un pezzo o None, unita' al singolare, al plurale)
COMUNI = [
    ("riso-cotto", "Riso cotto", 130, 2.7, 28, 0.3, None, "", ""),
    ("pasta-cotta", "Pasta cotta, senza condimento", 150, 5.5, 30, 0.9, None, "", ""),
    ("pollo-cotto", "Petto di pollo cotto", 165, 31, 0, 3.6, None, "", ""),
    ("tacchino-cotto", "Tacchino cotto", 150, 29, 0, 3.5, None, "", ""),
    ("patate-lesse", "Patate lesse", 86, 1.9, 19, 0.1, None, "", ""),
    ("pane", "Pane", 275, 9, 55, 1.5, 30, "fetta", "fette"),
    ("piadina", "Piadina", 320, 7.5, 50, 10, 110, "piadina", "piadine"),
    ("cracker", "Cracker", 430, 10, 70, 11, 25, "pacchetto", "pacchetti"),
    ("cereali", "Cereali da colazione", 375, 7, 82, 1.5, 30, "porzione", "porzioni"),
    ("prosciutto-cotto", "Prosciutto cotto", 130, 20, 1, 5, 20, "fetta", "fette"),
    ("prosciutto-crudo", "Prosciutto crudo", 225, 27, 0, 13, 15, "fetta", "fette"),
    ("bresaola", "Bresaola", 150, 32, 0, 2, 10, "fetta", "fette"),
    ("mortadella", "Mortadella", 310, 15, 1, 28, 15, "fetta", "fette"),
    ("salame", "Salame", 390, 26, 1, 31, 8, "fetta", "fette"),
    ("wurstel", "Würstel di pollo", 250, 13, 2, 21, 50, "würstel", "würstel"),
    ("mela", "Mela", 52, 0.3, 13.5, 0.2, 180, "mela", "mele"),
    ("arancia", "Arancia", 47, 0.9, 11, 0.1, 200, "arancia", "arance"),
    ("pera", "Pera", 57, 0.4, 14.5, 0.1, 170, "pera", "pere"),
    ("kiwi", "Kiwi", 61, 1.1, 14, 0.5, 80, "kiwi", "kiwi"),
    ("fragole", "Fragole", 32, 0.7, 7, 0.3, None, "", ""),
    ("uva", "Uva", 67, 0.6, 17, 0.2, None, "", ""),
    ("anguria", "Anguria", 30, 0.6, 7.5, 0.2, None, "", ""),
    ("mandorle", "Mandorle", 600, 21, 8, 52, None, "", ""),
    ("arachidi", "Arachidi tostate", 600, 26, 10, 50, None, "", ""),
    ("avocado", "Avocado", 160, 2, 3, 15, 140, "avocado", "avocado"),
    ("latte-sl", "Latte senza lattosio parzialmente scremato", 46, 3.3, 5, 1.6, 200, "bicchiere", "bicchieri"),
    ("bevanda-soia", "Bevanda di soia", 40, 3.3, 2, 1.9, 200, "bicchiere", "bicchieri"),
    ("marmellata", "Marmellata", 250, 0.5, 60, 0.1, 15, "cucchiaino", "cucchiaini"),
    ("miele", "Miele", 304, 0.3, 80, 0, 10, "cucchiaino", "cucchiaini"),
    ("crema-nocciole", "Crema di nocciole", 539, 6.3, 57.5, 30.9, 15, "cucchiaino", "cucchiaini"),
    ("burro-arachidi", "Burro di arachidi", 600, 25, 12, 50, 15, "cucchiaino", "cucchiaini"),
    ("zucchero", "Zucchero", 400, 0, 100, 0, 5, "bustina", "bustine"),
    ("maionese", "Maionese", 680, 1, 2, 75, 15, "cucchiaio", "cucchiai"),
    ("ketchup", "Ketchup", 100, 1.2, 23, 0.1, 15, "cucchiaio", "cucchiai"),
    ("glassa", "Glassa di aceto balsamico", 190, 0.8, 44, 0, 10, "cucchiaino", "cucchiaini"),
]

MUSCOLI = {
    "petto_alto": "Petto alto", "petto": "Petto", "spalle_ant": "Spalle anteriori",
    "spalle_lat": "Spalle laterali", "spalle_post": "Spalle posteriori", "bicipiti": "Bicipiti",
    "tricipiti": "Tricipiti", "avambracci": "Avambracci", "addome": "Addome", "obliqui": "Obliqui",
    "dorsali": "Dorsali", "dorso_alto": "Dorso alto", "lombari": "Lombari", "glutei": "Glutei",
    "quadricipiti": "Quadricipiti", "femorali": "Femorali", "polpacci": "Polpacci", "adduttori": "Interno coscia",
}

ESERCIZI = {
    "incline-db-press": {
        "n": "Panca inclinata con manubri", "att": "Panca a 30° e manubri",
        "m1": ["petto_alto", "petto"], "m2": ["spalle_ant", "tricipiti"],
        "come": ["Panca a 30°, non di più: oltre lavora la spalla.",
                 "Scapole strette e basse, petto in fuori, piedi a terra.",
                 "Scendi in 2-3 secondi con i gomiti a 45° dal busto.",
                 "Spingi verso l'alto e un po' verso l'interno, senza far toccare i manubri."],
        "no": ["Inarcare la schiena fino a farla diventare una panca piana.", "Rimbalzare in basso."],
        "alt": ["smith-incline-press", "incline-chest-press"],
    },
    "lat-pulldown": {
        "n": "Lat machine presa larga", "att": "Lat machine con barra larga",
        "m1": ["dorsali"], "m2": ["bicipiti", "dorso_alto", "spalle_post"],
        "come": ["Presa poco più larga delle spalle, cosce bloccate sotto i cuscinetti.",
                 "Busto appena inclinato indietro, petto verso la barra.",
                 "Tira portando i gomiti verso i fianchi: la barra arriva sotto il mento.",
                 "Risali lento fino a braccia quasi distese."],
        "no": ["Dondolare con il busto per aiutarti.", "Tirare la barra dietro la nuca."],
        "alt": ["closegrip-pulldown", "vbar-pulldown"],
    },
    "leg-press": {
        "n": "Leg press", "att": "Pressa a 45°",
        "m1": ["quadricipiti", "glutei"], "m2": ["femorali"],
        "come": ["Piedi alla larghezza delle spalle, a metà pedana.",
                 "Scendi finché le ginocchia arrivano verso il petto senza staccare il bacino.",
                 "Spingi con tutto il piede, soprattutto il tallone.",
                 "In alto non bloccare le ginocchia."],
        "no": ["Sollevare il sedere dallo schienale in fondo.", "Mezzo movimento con troppo carico."],
        "alt": ["smith-squat", "hack-squat"],
    },
    "seated-leg-curl": {
        "n": "Leg curl seduto", "att": "Macchina leg curl seduto",
        "m1": ["femorali"], "m2": ["polpacci"],
        "come": ["Ginocchio allineato al perno della macchina, cuscino sopra il tallone.",
                 "Blocca le cosce con il fermo.",
                 "Piega fino in fondo e stringi un secondo.",
                 "Torna su in 3 secondi senza far sbattere i pesi."],
        "no": ["Staccare il sedere dal sedile.", "Usare lo slancio."],
        "alt": ["lying-leg-curl"],
    },
    "lateral-raise": {
        "n": "Alzate laterali con manubri", "att": "Manubri",
        "m1": ["spalle_lat"], "m2": ["dorso_alto"],
        "come": ["Busto appena inclinato in avanti, gomiti leggermente piegati.",
                 "Alza verso l'esterno fino all'altezza delle spalle, guidando con i gomiti.",
                 "In alto il mignolo è appena più alto del pollice.",
                 "Scendi in 2-3 secondi: è lì che lavora di più."],
        "no": ["Carico troppo alto e slancio con la schiena.", "Alzare le spalle verso le orecchie."],
        "alt": ["seated-lateral-raise"],
    },
    "rope-pushdown": {
        "n": "Pushdown tricipiti alla corda", "att": "Cavo alto con corda",
        "m1": ["tricipiti"], "m2": [],
        "come": ["Gomiti incollati ai fianchi, busto appena inclinato.",
                 "Spingi in basso e apri la corda in fondo.",
                 "Stringi un secondo a braccia distese.",
                 "Risali fino a 90° senza muovere i gomiti."],
        "no": ["Far salire e scendere i gomiti.", "Spingere con le spalle chinandoti sul cavo."],
        "alt": ["bar-pushdown"],
    },
    "incline-curl": {
        "n": "Curl su panca inclinata", "att": "Panca a 60° e manubri",
        "m1": ["bicipiti"], "m2": ["avambracci"],
        "come": ["Schiena appoggiata, braccia che pendono dietro il busto.",
                 "Piega senza portare i gomiti in avanti.",
                 "Ruota il palmo verso l'alto mentre sali.",
                 "Scendi fino a distendere quasi del tutto."],
        "no": ["Staccare le spalle dallo schienale.", "Fermarti a metà discesa."],
        "alt": ["db-curl"],
    },
    "plank": {
        "n": "Plank", "att": "Tappetino", "tempo": True,
        "m1": ["addome"], "m2": ["obliqui", "lombari"],
        "come": ["Gomiti sotto le spalle, corpo in linea retta.",
                 "Ruota il bacino indietro e stringi i glutei: è il gesto che corregge la tua postura.",
                 "Spingi il pavimento con gli avambracci.",
                 "Respira normalmente e fermati quando la schiena cede."],
        "no": ["Sedere troppo alto o schiena insellata.", "Trattenere il fiato."],
        "alt": ["cable-crunch"],
    },
    "cable-row": {
        "n": "Pulley basso", "att": "Pulley con triangolo",
        "m1": ["dorso_alto", "dorsali"], "m2": ["bicipiti", "spalle_post", "lombari"],
        "come": ["Seduto con le ginocchia morbide e la schiena dritta.",
                 "Tira il triangolo verso l'ombelico, gomiti vicini al busto.",
                 "Stringi le scapole per un secondo.",
                 "Allunga le braccia lasciando avanzare le scapole, senza curvare la schiena."],
        "no": ["Dondolare avanti e indietro con il busto.", "Alzare le spalle."],
        "alt": ["db-row"],
    },
    "shoulder-press-machine": {
        "n": "Shoulder press", "att": "Macchina shoulder press",
        "m1": ["spalle_ant", "spalle_lat"], "m2": ["tricipiti", "petto_alto"],
        "come": ["Regola il sedile: le maniglie partono all'altezza delle orecchie.",
                 "Schiena appoggiata, addome contratto.",
                 "Spingi in alto senza bloccare i gomiti.",
                 "Scendi controllato fino a gomiti poco sotto le spalle."],
        "no": ["Inarcare la schiena staccandola dallo schienale.", "Mezza escursione."],
        "alt": ["db-shoulder-press"],
    },
    "db-rdl": {
        "n": "Stacco rumeno con manubri", "att": "Manubri",
        "m1": ["femorali", "glutei"], "m2": ["lombari", "dorso_alto"],
        "come": ["Piedi alla larghezza dei fianchi, ginocchia appena piegate e ferme.",
                 "Spingi il sedere indietro come per chiudere una porta, schiena piatta.",
                 "I manubri scendono lungo le cosce fino a metà tibia.",
                 "Risali spingendo i fianchi in avanti e stringendo i glutei."],
        "no": ["Curvare la schiena.", "Piegare le ginocchia fino a farlo diventare uno squat."],
        "alt": ["barbell-rdl"],
    },
    "chest-press": {
        "n": "Chest press", "att": "Macchina chest press",
        "m1": ["petto"], "m2": ["spalle_ant", "tricipiti"],
        "come": ["Maniglie all'altezza di metà petto.",
                 "Scapole strette contro lo schienale.",
                 "Spingi senza bloccare i gomiti.",
                 "Torna indietro lento fino a sentire il petto allungarsi."],
        "no": ["Staccare le spalle dallo schienale per spingere.", "Gomiti troppo alti."],
        "alt": ["db-bench-press"],
    },
    "leg-extension": {
        "n": "Leg extension", "att": "Macchina leg extension",
        "m1": ["quadricipiti"], "m2": [],
        "come": ["Ginocchio allineato al perno, cuscino sopra la caviglia.",
                 "Distendi fino in fondo e stringi un secondo.",
                 "Scendi in 3 secondi.",
                 "Tieni le maniglie per non staccarti dal sedile."],
        "no": ["Calciare il peso con lo slancio.", "Scendere di colpo."],
        "alt": [],
    },
    "reverse-pec-deck": {
        "n": "Deltoidi posteriori alla pec deck", "att": "Pec deck al contrario",
        "m1": ["spalle_post"], "m2": ["dorso_alto"],
        "come": ["Petto contro il cuscino, maniglie all'altezza delle spalle.",
                 "Apri le braccia verso l'esterno con i gomiti appena piegati.",
                 "Fermati quando le braccia sono in linea con le spalle.",
                 "Torna lento, senza far toccare i pesi."],
        "no": ["Stringere le scapole e tirare con la schiena.", "Carico troppo alto."],
        "alt": ["reverse-fly", "face-pull"],
    },
    "calf-raise": {
        "n": "Calf in piedi", "att": "Calf machine",
        "m1": ["polpacci"], "m2": [],
        "come": ["Avampiede sul gradino, talloni fuori.",
                 "Scendi fino a sentire l'allungamento e fermati un secondo.",
                 "Sali più in alto che puoi sulle punte.",
                 "Ginocchia quasi tese per tutto il movimento."],
        "no": ["Rimbalzare.", "Fare mezzi movimenti."],
        "alt": ["calf-press"],
    },
    "cable-crunch": {
        "n": "Crunch al cavo", "att": "Cavo alto con corda",
        "m1": ["addome"], "m2": ["obliqui"],
        "come": ["In ginocchio davanti al cavo, corda ai lati della testa.",
                 "Arrotola la schiena portando i gomiti verso le ginocchia.",
                 "Il bacino resta fermo: non sederti sui talloni.",
                 "Risali lento fino a distendere l'addome."],
        "no": ["Tirare con le braccia.", "Muovere i fianchi invece di arrotolare il busto."],
        "alt": ["crunch-machine"],
    },
    "incline-chest-press": {
        "n": "Chest press inclinata", "att": "Macchina chest press inclinata",
        "m1": ["petto_alto", "petto"], "m2": ["spalle_ant", "tricipiti"],
        "come": ["Maniglie all'altezza della parte alta del petto.",
                 "Scapole strette e basse.",
                 "Spingi in alto in linea con le clavicole.",
                 "Discesa in 3 secondi."],
        "no": ["Spalle che avanzano a fine spinta.", "Sedile troppo basso: lavorano solo le spalle."],
        "alt": ["smith-incline-press", "incline-db-press"],
    },
    "vbar-pulldown": {
        "n": "Lat machine con triangolo", "att": "Lat machine con triangolo",
        "m1": ["dorsali"], "m2": ["bicipiti", "dorso_alto"],
        "come": ["Presa stretta con i palmi uno di fronte all'altro, busto appena indietro.",
                 "Tira il triangolo verso la parte alta del petto.",
                 "I gomiti scendono lungo i fianchi.",
                 "Risali lento fino a braccia distese."],
        "no": ["Tirare con le braccia invece che con i gomiti.", "Dondolare."],
        "alt": ["closegrip-pulldown", "lat-pulldown"],
    },
    "hack-squat": {
        "n": "Hack squat", "att": "Macchina hack squat",
        "m1": ["quadricipiti", "glutei"], "m2": ["femorali"],
        "come": ["Schiena e testa appoggiate, piedi a metà pedana.",
                 "Scendi fino ad avere le cosce parallele alla pedana.",
                 "Ginocchia nella direzione delle punte.",
                 "Spingi senza bloccare le ginocchia in alto."],
        "no": ["Talloni che si staccano.", "Ginocchia che cedono verso l'interno."],
        "alt": ["goblet-squat", "smith-squat", "leg-press"],
    },
    "hip-thrust": {
        "n": "Hip thrust", "att": "Panca e bilanciere, o macchina hip thrust",
        "m1": ["glutei"], "m2": ["femorali", "addome"],
        "come": ["Scapole sul bordo della panca, bilanciere sull'anca con il cuscinetto.",
                 "Piedi alla larghezza dei fianchi: in alto le tibie sono verticali.",
                 "Sali spingendo sui talloni fino ad avere busto e cosce in linea.",
                 "In alto mento basso, costole chiuse e glutei stretti un secondo."],
        "no": ["Inarcare la schiena invece di estendere l'anca.", "Spingere sulle punte."],
        "alt": [],
    },
    "seated-lateral-raise": {
        "n": "Alzate laterali da seduto", "att": "Panca e manubri",
        "m1": ["spalle_lat"], "m2": ["dorso_alto"],
        "come": ["Seduto in punta di panca, busto fermo.",
                 "Alza fino all'altezza delle spalle con i gomiti morbidi.",
                 "Fermati un attimo in alto.",
                 "Scendi in 3 secondi."],
        "no": ["Usare il busto per dare slancio.", "Alzare oltre le spalle scrollandole."],
        "alt": ["lateral-raise"],
    },
    "face-pull": {
        "n": "Face pull", "att": "Cavo alto con corda",
        "m1": ["spalle_post", "dorso_alto"], "m2": ["bicipiti"],
        "come": ["Cavo all'altezza degli occhi, pollici rivolti verso di te.",
                 "Tira la corda verso il viso aprendola ai lati delle orecchie.",
                 "Gomiti alti, in linea con le spalle.",
                 "Chiudi ruotando le mani indietro, poi torna lento."],
        "no": ["Tirare verso il petto.", "Inclinare il busto indietro."],
        "alt": ["reverse-fly", "reverse-pec-deck"],
    },
    "overhead-triceps": {
        "n": "Estensioni tricipiti sopra la testa", "att": "Cavo con corda",
        "m1": ["tricipiti"], "m2": [],
        "come": ["Spalle al cavo, un piede avanti, corda dietro la nuca.",
                 "Gomiti stretti e puntati in avanti.",
                 "Distendi le braccia sopra la testa.",
                 "Torna giù finché l'avambraccio tocca il bicipite."],
        "no": ["Aprire i gomiti verso l'esterno.", "Inarcare la schiena."],
        "alt": ["rope-pushdown"],
    },
    "hammer-curl": {
        "n": "Hammer curl", "att": "Manubri",
        "m1": ["bicipiti", "avambracci"], "m2": [],
        "come": ["Palmi rivolti verso il corpo per tutto il movimento.",
                 "Gomiti fermi ai fianchi.",
                 "Sali fino all'altezza della spalla.",
                 "Scendi lento fino a braccio disteso."],
        "no": ["Dondolare con il busto.", "Portare i gomiti in avanti."],
        "alt": ["db-curl"],
    },
    "knee-raise": {
        "n": "Ginocchia al petto alle parallele", "att": "Sedia romana",
        "m1": ["addome"], "m2": ["obliqui"],
        "come": ["Avambracci sui cuscini, schiena appoggiata.",
                 "Porta le ginocchia verso il petto arrotolando il bacino.",
                 "Il movimento finisce quando il sedere si stacca dallo schienale.",
                 "Scendi lento senza far oscillare le gambe."],
        "no": ["Sollevare solo le gambe senza arrotolare il bacino.", "Dondolare."],
        "alt": ["hanging-leg-raise"],
    },
    # ---- alternative
    "smith-incline-press": {
        "n": "Panca inclinata al multipower", "att": "Multipower e panca a 30°",
        "m1": ["petto_alto", "petto"], "m2": ["spalle_ant", "tricipiti"],
        "come": ["Panca a 30° sotto il bilanciere, che scende sulla parte alta del petto.",
                 "Presa poco più larga delle spalle, scapole strette.",
                 "Spingi in verticale senza staccare le spalle dalla panca."],
        "no": ["Far rimbalzare il bilanciere sul petto."], "alt": [],
    },
    "closegrip-pulldown": {
        "n": "Lat machine presa stretta", "att": "Lat machine",
        "m1": ["dorsali"], "m2": ["bicipiti", "dorso_alto"],
        "come": ["Presa alla larghezza delle spalle.",
                 "Tira verso la parte alta del petto con i gomiti lungo i fianchi.",
                 "Risali lento."],
        "no": ["Dondolare con il busto."], "alt": [],
    },
    "smith-squat": {
        "n": "Squat al multipower", "att": "Multipower",
        "m1": ["quadricipiti", "glutei"], "m2": ["femorali", "lombari"],
        "come": ["Bilanciere sui trapezi, piedi appena avanti rispetto al bilanciere.",
                 "Scendi fino a cosce parallele con la schiena dritta.",
                 "Spingi sui talloni."],
        "no": ["Ginocchia che cedono verso l'interno."], "alt": [],
    },
    "lying-leg-curl": {
        "n": "Leg curl sdraiato", "att": "Macchina leg curl sdraiato",
        "m1": ["femorali"], "m2": ["polpacci"],
        "come": ["Cuscino sopra il tallone, bacino premuto sul lettino.",
                 "Piega fino quasi a toccare i glutei.",
                 "Scendi in 3 secondi."],
        "no": ["Alzare il sedere per aiutarti."], "alt": [],
    },
    "bar-pushdown": {
        "n": "Pushdown alla barra", "att": "Cavo alto con barra",
        "m1": ["tricipiti"], "m2": [],
        "come": ["Gomiti ai fianchi.", "Spingi fino a braccia distese.", "Risali a 90°."],
        "no": ["Muovere i gomiti."], "alt": [],
    },
    "db-curl": {
        "n": "Curl con manubri in piedi", "att": "Manubri",
        "m1": ["bicipiti"], "m2": ["avambracci"],
        "come": ["Gomiti fermi ai fianchi.", "Sali ruotando il palmo verso l'alto.", "Scendi lento."],
        "no": ["Dondolare con il busto."], "alt": [],
    },
    "db-row": {
        "n": "Rematore con manubrio", "att": "Panca e manubrio",
        "m1": ["dorsali", "dorso_alto"], "m2": ["bicipiti", "spalle_post"],
        "come": ["Mano e ginocchio sulla panca, schiena piatta.",
                 "Tira il manubrio verso l'anca.",
                 "Scendi lasciando allungare la scapola."],
        "no": ["Ruotare il busto per tirare su il peso."], "alt": [],
    },
    "db-shoulder-press": {
        "n": "Lento avanti con manubri", "att": "Panca a 80° e manubri",
        "m1": ["spalle_ant", "spalle_lat"], "m2": ["tricipiti"],
        "come": ["Schiena appoggiata, manubri all'altezza delle orecchie.",
                 "Spingi in alto senza farli toccare.",
                 "Scendi controllato."],
        "no": ["Inarcare la schiena."], "alt": [],
    },
    "barbell-rdl": {
        "n": "Stacco rumeno con bilanciere", "att": "Bilanciere",
        "m1": ["femorali", "glutei"], "m2": ["lombari"],
        "come": ["Bilanciere a contatto con le cosce.",
                 "Sedere indietro, schiena piatta.",
                 "Scendi fino a metà tibia."],
        "no": ["Curvare la schiena."], "alt": [],
    },
    "db-bench-press": {
        "n": "Panca piana con manubri", "att": "Panca e manubri",
        "m1": ["petto"], "m2": ["spalle_ant", "tricipiti"],
        "come": ["Scapole strette, piedi a terra.",
                 "Scendi con i gomiti a 45° dal busto.",
                 "Spingi senza far toccare i manubri."],
        "no": ["Rimbalzare in basso."], "alt": [],
    },
    "reverse-fly": {
        "n": "Aperture posteriori con manubri", "att": "Panca inclinata e manubri",
        "m1": ["spalle_post"], "m2": ["dorso_alto"],
        "come": ["Petto sulla panca inclinata.",
                 "Apri le braccia di lato con i gomiti morbidi.",
                 "Carico leggero, movimento lento."],
        "no": ["Usare lo slancio."], "alt": [],
    },
    "calf-press": {
        "n": "Calf alla pressa", "att": "Leg press",
        "m1": ["polpacci"], "m2": [],
        "come": ["Solo l'avampiede sul bordo della pedana.",
                 "Spingi sulle punte, poi scendi in allungamento.",
                 "Ginocchia quasi tese."],
        "no": ["Rimbalzare."], "alt": [],
    },
    "crunch-machine": {
        "n": "Crunch alla macchina", "att": "Macchina ab crunch",
        "m1": ["addome"], "m2": ["obliqui"],
        "come": ["Arrotola il busto verso le ginocchia.", "Non tirare con le braccia.", "Risali lento."],
        "no": ["Usare lo slancio."], "alt": [],
    },
    "goblet-squat": {
        "n": "Goblet squat", "att": "Manubrio o kettlebell",
        "m1": ["quadricipiti", "glutei"], "m2": ["addome"],
        "come": ["Peso contro il petto, gomiti bassi.",
                 "Scendi tra le ginocchia tenendo il busto dritto.",
                 "Spingi sui talloni."],
        "no": ["Talloni che si staccano."], "alt": [],
    },
    "hanging-leg-raise": {
        "n": "Ginocchia al petto alla sbarra", "att": "Sbarra",
        "m1": ["addome"], "m2": ["obliqui", "avambracci"],
        "come": ["Appeso senza oscillare.",
                 "Porta le ginocchia al petto arrotolando il bacino.",
                 "Scendi lento."],
        "no": ["Dondolare."], "alt": [],
    },
}

# ---- a corpo libero, per chi si allena a casa
ESERCIZI.update({
    "push-up": {
        "n": "Piegamenti sulle braccia", "att": "Corpo libero", "corpo": True,
        "m1": ["petto"], "m2": ["tricipiti", "spalle_ant", "addome"],
        "come": ["Mani poco più larghe delle spalle, corpo in linea dalla testa ai talloni.",
                 "Scendi in due secondi finché il petto sfiora il pavimento, gomiti a 45° dal busto.",
                 "Spingi il pavimento e torna su senza perdere la linea.",
                 "Troppo duri? Appoggia le ginocchia, oppure le mani su un rialzo."],
        "no": ["Far cadere i fianchi o alzare il sedere.", "Aprire i gomiti a 90°, come una T."],
        "alt": ["chair-dip"],
    },
    "bodyweight-squat": {
        "n": "Squat a corpo libero", "att": "Corpo libero", "corpo": True,
        "m1": ["quadricipiti", "glutei"], "m2": ["femorali", "lombari"],
        "come": ["Piedi larghi come le spalle, punte un po' in fuori.",
                 "Scendi come per sederti, ginocchia nella direzione delle punte.",
                 "Arriva almeno con le cosce parallele al pavimento, talloni a terra.",
                 "Risali spingendo sui talloni e stringi i glutei in alto."],
        "no": ["Ginocchia che cedono verso l'interno.", "Talloni che si staccano o schiena che si incurva."],
        "alt": ["reverse-lunge"],
    },
    "reverse-lunge": {
        "n": "Affondi indietro", "att": "Corpo libero", "corpo": True,
        "m1": ["quadricipiti", "glutei"], "m2": ["femorali", "polpacci"],
        "come": ["In piedi, fai un passo lungo indietro con una gamba.",
                 "Scendi finché il ginocchio dietro sfiora il pavimento, busto dritto.",
                 "Spingi sul tallone della gamba davanti per tornare su.",
                 "Finisci le ripetizioni di una gamba, poi cambia."],
        "no": ["Passo troppo corto: il ginocchio davanti si carica male.", "Spingersi con la gamba dietro."],
        "alt": ["bodyweight-squat"],
    },
    "glute-bridge": {
        "n": "Ponte per i glutei", "att": "Tappetino", "corpo": True,
        "m1": ["glutei"], "m2": ["femorali", "lombari"],
        "come": ["Sulla schiena, ginocchia piegate, piedi vicini al sedere.",
                 "Spingi sui talloni e alza il bacino finché spalle, fianchi e ginocchia sono in linea.",
                 "Stringi forte i glutei per un secondo in alto.",
                 "Scendi piano senza appoggiare del tutto."],
        "no": ["Inarcare la schiena per salire di più.", "Spingere sulle punte dei piedi."],
        "alt": [],
    },
    "superman": {
        "n": "Superman", "att": "Tappetino", "corpo": True,
        "m1": ["lombari"], "m2": ["glutei", "dorso_alto", "spalle_post"],
        "come": ["A pancia in giù, braccia distese in avanti.",
                 "Alza insieme braccia, petto e gambe di pochi centimetri.",
                 "Tieni due secondi stringendo glutei e schiena.",
                 "Torna giù piano, sguardo sempre al pavimento."],
        "no": ["Piegare il collo all'indietro.", "Strappare verso l'alto."],
        "alt": [],
    },
    "bicycle-crunch": {
        "n": "Crunch a bicicletta", "att": "Tappetino", "corpo": True,
        "m1": ["addome", "obliqui"], "m2": [],
        "come": ["Sulla schiena, mani dietro la testa, gambe sollevate.",
                 "Porta il gomito verso il ginocchio opposto mentre distendi l'altra gamba.",
                 "Ruota il busto, non solo il gomito, e cambia lato senza fretta.",
                 "La parte bassa della schiena resta sempre appoggiata."],
        "no": ["Tirare il collo con le mani.", "Andare veloce pedalando a vuoto."],
        "alt": ["plank"],
    },
    "mountain-climber": {
        "n": "Mountain climber", "att": "Corpo libero", "corpo": True, "tempo": True,
        "m1": ["addome"], "m2": ["quadricipiti", "spalle_ant", "obliqui"],
        "come": ["Posizione di plank a braccia tese, mani sotto le spalle.",
                 "Porta un ginocchio al petto e torna indietro, poi l'altro, a ritmo.",
                 "Fianchi bassi e fermi, addome contratto.",
                 "Parti piano e accelera solo se resti in linea."],
        "no": ["Sedere in alto.", "Saltellare perdendo la linea delle spalle."],
        "alt": ["jumping-jack"],
    },
    "chair-dip": {
        "n": "Dip alla sedia", "att": "Una sedia stabile", "corpo": True,
        "m1": ["tricipiti"], "m2": ["petto", "spalle_ant"],
        "come": ["Mani sul bordo della sedia ai lati dei fianchi, gambe avanti.",
                 "Scendi piegando i gomiti all'indietro fino a circa 90°.",
                 "Schiena vicina alla sedia per tutto il movimento.",
                 "Risali distendendo le braccia; con le gambe tese è più dura."],
        "no": ["Scendere troppo: le spalle ruotano in avanti.", "Usare una sedia che scivola."],
        "alt": ["push-up"],
    },
    "jumping-jack": {
        "n": "Jumping jack", "att": "Corpo libero", "corpo": True, "tempo": True,
        "m1": ["polpacci", "spalle_lat"], "m2": ["quadricipiti"],
        "come": ["In piedi, braccia lungo i fianchi.",
                 "Salta aprendo le gambe e porta le braccia sopra la testa.",
                 "Torna alla partenza con un altro saltello.",
                 "Atterra morbido sugli avampiedi, ginocchia un po' piegate."],
        "no": ["Atterrare rigido sui talloni.", "Trattenere il fiato."],
        "alt": ["mountain-climber"],
    },
})

# ---- bilanciere, macchine e addominali a terra: arrivano dalla scheda di una persona, ma stanno nel catalogo per tutti
ESERCIZI.update({
    "bench-press": {
        "n": "Panca piana con bilanciere", "att": "Panca e bilanciere",
        "m1": ["petto"], "m2": ["tricipiti", "spalle_ant"],
        "come": ["Scapole strette e basse, piedi ben piantati, un leggero arco nella schiena.",
                 "Presa poco più larga delle spalle: stacca il bilanciere e portalo sopra il petto.",
                 "Scendi controllato fino a sfiorare il petto, gomiti a circa 45° dal busto.",
                 "Spingi in alto e leggermente indietro, senza staccare il sedere dalla panca."],
        "no": ["Far rimbalzare il bilanciere sul petto.", "Gomiti larghi a 90°: caricano le spalle."],
        "alt": ["chest-press", "db-bench-press"],
    },
    "incline-bench-press": {
        "n": "Panca inclinata con bilanciere", "att": "Panca a 30° e bilanciere",
        "m1": ["petto_alto", "petto"], "m2": ["spalle_ant", "tricipiti"],
        "come": ["Panca a 30°, scapole strette e basse.",
                 "Stacca il bilanciere e portalo sopra la parte alta del petto.",
                 "Scendi controllato verso le clavicole, gomiti a 45°.",
                 "Spingi in verticale senza perdere la posizione delle spalle."],
        "no": ["Panca troppo inclinata: lavora la spalla.", "Staccare il sedere per aiutarti."],
        "alt": ["smith-incline-press", "incline-db-press"],
    },
    "fly": {
        "n": "Fly con manubri", "att": "Panca e manubri",
        "m1": ["petto"], "m2": ["spalle_ant"],
        "come": ["Sulla panca, manubri sopra il petto, gomiti appena piegati.",
                 "Apri le braccia ad arco finché senti il petto allungarsi, senza scendere sotto le spalle.",
                 "Richiudi come per abbracciare un albero, stringendo il petto in alto.",
                 "Movimento lento: qui conta il controllo, non il carico."],
        "no": ["Piegare i gomiti fino a farla diventare una panca.", "Scendere troppo: la spalla soffre."],
        "alt": ["chest-press"],
    },
    "lever-row": {
        "n": "Rowing alla macchina", "att": "Macchina a leve con dischi",
        "m1": ["dorsali", "dorso_alto"], "m2": ["bicipiti", "spalle_post"],
        "come": ["Petto contro il supporto, sedile regolato perché le maniglie siano all'altezza dello sterno.",
                 "Tira portando i gomiti indietro e stringendo le scapole.",
                 "Un secondo di pausa in chiusura.",
                 "Torna avanti controllato, allungando bene il dorso."],
        "no": ["Staccare il petto dal supporto per tirare con la schiena.", "Tirare a strappi."],
        "alt": ["cable-row", "db-row"],
    },
    "bulgarian-split-squat": {
        "n": "Bulgarian split squat", "att": "Panca, a corpo libero", "corpo": True,
        "m1": ["quadricipiti", "glutei"], "m2": ["femorali"],
        "come": ["Un piede dietro appoggiato sulla panca, l'altro avanti di un passo lungo.",
                 "Scendi in verticale finché la coscia davanti è parallela al pavimento.",
                 "Busto appena in avanti, peso sul tallone davanti.",
                 "Risali spingendo con la gamba davanti; finite le ripetizioni cambia gamba."],
        "no": ["Piede davanti troppo vicino alla panca.", "Ginocchio che cede verso l'interno."],
        "alt": ["reverse-lunge", "bodyweight-squat"],
    },
    "single-leg-curl": {
        "n": "Leg curl a una gamba", "att": "Macchina leg curl",
        "m1": ["femorali"], "m2": ["polpacci"],
        "come": ["Regola il rullo appena sopra il tallone.",
                 "Piega una gamba sola portando il tallone verso il gluteo.",
                 "Stringi un secondo in chiusura.",
                 "Torna giù in due o tre secondi; finite le ripetizioni cambia gamba."],
        "no": ["Aiutarsi inarcando la schiena.", "Lasciar cadere il peso."],
        "alt": ["lying-leg-curl", "seated-leg-curl"],
    },
    "adductor": {
        "n": "Adductor machine", "att": "Macchina per l'interno coscia",
        "m1": ["adduttori"], "m2": [],
        "come": ["Seduto con la schiena appoggiata, cuscinetti all'interno delle ginocchia.",
                 "Chiudi le gambe stringendo l'interno coscia.",
                 "Un secondo di pausa a gambe chiuse.",
                 "Riapri lentamente, senza far sbattere i pesi."],
        "no": ["Aprire più di quanto riesci a controllare.", "Usare lo slancio."],
        "alt": [],
    },
    "abductor": {
        "n": "Abductor machine", "att": "Macchina per l'esterno coscia",
        "m1": ["glutei"], "m2": [],
        "come": ["Seduto con la schiena appoggiata, cuscinetti all'esterno delle ginocchia.",
                 "Apri le gambe spingendo con l'esterno coscia e i glutei.",
                 "Un secondo di pausa in apertura.",
                 "Richiudi lentamente, senza far sbattere i pesi."],
        "no": ["Staccare la schiena dallo schienale.", "Andare veloce, a rimbalzo."],
        "alt": ["hip-thrust"],
    },
    "front-plate-raise": {
        "n": "Alzate frontali con disco", "att": "Disco",
        "m1": ["spalle_ant"], "m2": ["spalle_lat", "petto_alto"],
        "come": ["In piedi, disco tenuto ai lati con le due mani, braccia quasi tese.",
                 "Alza il disco davanti a te fino all'altezza degli occhi.",
                 "Fermati un attimo in alto senza inarcare la schiena.",
                 "Scendi in due o tre secondi."],
        "no": ["Dondolare con il busto per aiutarti.", "Salire sopra la testa."],
        "alt": ["lateral-raise"],
    },
    "upright-row": {
        "n": "Tirate al mento con EZ", "att": "Bilanciere EZ",
        "m1": ["spalle_lat", "dorso_alto"], "m2": ["bicipiti", "spalle_ant"],
        "come": ["In piedi, presa larga quanto le spalle, bilanciere davanti alle cosce.",
                 "Tira su il bilanciere lungo il corpo, guidando con i gomiti.",
                 "Fermati quando i gomiti sono all'altezza delle spalle.",
                 "Scendi controllato."],
        "no": ["Gomiti molto più alti delle spalle: schiacciano l'articolazione.", "Presa troppo stretta."],
        "alt": ["lateral-raise", "face-pull"],
    },
    "cable-curl": {
        "n": "Curl al cavo basso con barra", "att": "Cavo basso con barra",
        "m1": ["bicipiti"], "m2": ["avambracci"],
        "come": ["In piedi davanti al cavo basso, gomiti fermi lungo i fianchi.",
                 "Piega le braccia portando la barra verso le spalle.",
                 "Stringi i bicipiti un secondo in alto.",
                 "Scendi lentamente fino a braccia quasi tese: il cavo tira per tutto il movimento."],
        "no": ["Portare i gomiti in avanti.", "Dondolare con la schiena."],
        "alt": ["db-curl", "hammer-curl"],
    },
    "concentration-curl": {
        "n": "Curl concentrato", "att": "Panca e manubrio",
        "m1": ["bicipiti"], "m2": ["avambracci"],
        "come": ["Seduto, gomito appoggiato all'interno della coscia.",
                 "Piega il braccio portando il manubrio verso la spalla.",
                 "Stringi il bicipite in alto, ruotando un po' il mignolo verso l'esterno.",
                 "Scendi lentamente fino a braccio quasi teso; poi cambia braccio."],
        "no": ["Staccare il gomito dalla coscia.", "Aiutarsi con la spalla."],
        "alt": ["db-curl", "incline-curl"],
    },
    "db-overhead-triceps": {
        "n": "Estensioni dietro la nuca con manubrio", "att": "Un manubrio",
        "m1": ["tricipiti"], "m2": [],
        "come": ["Seduto o in piedi, un manubrio tenuto con due mani sopra la testa.",
                 "Gomiti stretti e puntati in alto.",
                 "Scendi con il manubrio dietro la nuca piegando solo i gomiti.",
                 "Distendi le braccia senza bloccare i gomiti di scatto."],
        "no": ["Aprire i gomiti verso l'esterno.", "Inarcare la schiena."],
        "alt": ["overhead-triceps", "rope-pushdown"],
    },
    "crunch": {
        "n": "Crunch a terra", "att": "Tappetino", "corpo": True,
        "m1": ["addome"], "m2": ["obliqui"],
        "come": ["Sulla schiena, ginocchia piegate, mani ai lati della testa.",
                 "Stacca le spalle da terra accorciando l'addome.",
                 "Sguardo in alto, mento lontano dal petto.",
                 "Scendi piano senza appoggiare del tutto la testa."],
        "no": ["Tirare il collo con le mani.", "Salire fino a sedersi: lavorano i flessori dell'anca."],
        "alt": ["reverse-crunch", "plank"],
    },
    "reverse-crunch": {
        "n": "Crunch inverso", "att": "Tappetino", "corpo": True,
        "m1": ["addome"], "m2": ["obliqui"],
        "come": ["Sulla schiena, braccia lungo i fianchi, ginocchia piegate a 90°.",
                 "Porta le ginocchia verso il petto staccando il bacino da terra.",
                 "Stringi l'addome un secondo in alto.",
                 "Torna giù lentamente senza far cadere le gambe."],
        "no": ["Slanciare le gambe.", "Inarcare la schiena in discesa."],
        "alt": ["crunch", "plank"],
    },
    "leg-raise": {
        "n": "Leg raise", "att": "Tappetino o panca", "corpo": True,
        "m1": ["addome"], "m2": ["obliqui", "quadricipiti"],
        "come": ["Sulla schiena, gambe tese, mani lungo i fianchi o sotto il sedere.",
                 "Alza le gambe unite fino alla verticale.",
                 "Scendi lentamente, fermandoti poco prima di toccare terra.",
                 "La parte bassa della schiena resta sempre appoggiata."],
        "no": ["Inarcare la schiena quando le gambe scendono.", "Usare lo slancio."],
        "alt": ["reverse-crunch", "knee-raise"],
    },
    "stretching": {
        "n": "Stretching", "att": "Tappetino", "corpo": True, "tempo": True,
        "m1": ["femorali", "quadricipiti"], "m2": ["glutei", "polpacci", "lombari"],
        "come": ["A fine seduta, senza fretta.",
                 "Ogni posizione per 30-40 secondi, respirando.",
                 "Allunga femorali, quadricipiti, glutei e polpacci.",
                 "Arriva dove tira, non dove fa male."],
        "no": ["Molleggiare.", "Trattenere il fiato."],
        "alt": [],
    },
})

RISCALDAMENTO = ["5 minuti di cyclette o ellittica a ritmo tranquillo.",
                 "2 serie leggere del primo esercizio: metà carico, 10 ripetizioni."]

# es = [esercizio, serie, ripetizioni, recupero in secondi]
SCHEDE = {
    "A": {"n": "Total body A", "fuoco": "Petto alto e spalle", "giorno": 0, "durata": 65,
          "es": [["incline-db-press", 4, "6-10", 150], ["lat-pulldown", 4, "8-12", 120],
                 ["leg-press", 3, "8-12", 150], ["seated-leg-curl", 3, "10-12", 90],
                 ["lateral-raise", 3, "12-15", 60], ["rope-pushdown", 3, "10-15", 75],
                 ["incline-curl", 3, "10-12", 75], ["plank", 3, "30-60 s", 60]]},
    "B": {"n": "Total body B", "fuoco": "Dorso e gambe", "giorno": 2, "durata": 65,
          "es": [["cable-row", 4, "8-12", 120], ["shoulder-press-machine", 3, "8-10", 120],
                 ["db-rdl", 3, "8-12", 150], ["chest-press", 3, "8-12", 120],
                 ["leg-extension", 3, "12-15", 75], ["reverse-pec-deck", 3, "12-15", 60],
                 ["calf-raise", 3, "10-15", 60], ["cable-crunch", 3, "12-15", 60]]},
    "C": {"n": "Total body C", "fuoco": "Spalle, braccia e glutei", "giorno": 4, "durata": 70,
          "es": [["incline-chest-press", 3, "8-12", 120], ["vbar-pulldown", 3, "8-12", 120],
                 ["hack-squat", 3, "8-12", 150], ["hip-thrust", 3, "8-12", 120],
                 ["seated-lateral-raise", 4, "12-20", 60], ["face-pull", 3, "12-15", 60],
                 ["overhead-triceps", 3, "10-12", 75], ["hammer-curl", 3, "10-12", 75],
                 ["knee-raise", 3, "10-15", 60]]},
}

PUNTI_CARENTI = [
    {"t": "Spalle", "m": ["spalle_lat", "spalle_post"],
     "d": "La linea delle spalle è stretta rispetto alla vita. È il punto che cambia di più la silhouette: alzate laterali due volte a settimana e deltoidi posteriori in ogni scheda."},
    {"t": "Petto alto", "m": ["petto_alto", "petto"],
     "d": "Piatto, manca volume sotto la clavicola. Per questo le spinte sono quasi tutte inclinate."},
    {"t": "Dorso", "m": ["dorsali", "dorso_alto"],
     "d": "Manca la forma a V e le spalle sono un po' chiuse in avanti. Tirate verticali e orizzontali in ogni seduta."},
    {"t": "Braccia", "m": ["tricipiti", "bicipiti"],
     "d": "Sottili, soprattutto il tricipite, che è due terzi del braccio."},
    {"t": "Gambe e glutei", "m": ["quadricipiti", "femorali", "glutei"],
     "d": "Quadricipiti e femorali esili, glutei poco sviluppati."},
    {"t": "Addome basso", "m": ["addome", "obliqui"],
     "d": "Metà è grasso localizzato, metà è postura: il bacino ruota in avanti e l'addome è rilassato. Plank, glutei e camminata lo fanno rientrare."},
]

GUIDA = [
    {"id": "strategia", "t": "La strategia", "icona": "target", "p": [
        "L'obiettivo è togliere la pancia: mangi circa 350 calorie al giorno in meno di quelle che consumi, senza fretta.",
        "Le proteine restano alte e i pesi restano tre sere a settimana: è quello che fa perdere grasso e non muscolo.",
        "Parti da 62 kg, quindi non c'è molto da togliere: per questo il taglio è leggero. Tagliare di più ti farebbe solo più piccolo, con la pancia ancora lì.",
        "Traguardo: 58 kg, e soprattutto qualche centimetro in meno di giro vita. Lì ci si ferma e si decide come proseguire."]},
    {"id": "dieta", "t": "Regole della dieta", "icona": "fork", "p": [
        "I grammi sono sempre a crudo. Pesa il riso prima di cuocerlo.",
        "Nei giorni di palestra mangi un po' più riso, patate e tortillas. Nei giorni di riposo meno.",
        "Latte, mozzarella e fiocchi di latte solo senza lattosio. Il grana stagionato ne è già privo.",
        "Vellutata: senza panna, sotto 55 kcal e 0,8 g di sale per 100 g. È un contorno, accanto servono riso e pollo.",
        "Tortillas: il piano conta quelle medie da 40 g. Se le tue sono da 60 g, usane una in meno.",
        "Il cucchiaino d'olio a crudo e le noci non sono un optional: con così poco olio rischi di stare troppo basso di grassi.",
        "Una cena libera a settimana, senza sensi di colpa e senza compensare il giorno dopo.",
        "Bevi 2,3 litri d'acqua nei giorni di riposo e 2,8 in quelli di palestra: li conti dalla schermata Oggi."]},
    {"id": "tarare", "t": "Come tarare le quantità", "icona": "scale", "p": [
        "Pesati al mattino a digiuno 2-3 volte a settimana e guarda la media, non il singolo giorno.",
        "Misura il giro vita all'altezza dell'ombelico ogni due settimane.",
        "Il peso deve scendere di tre o quattro etti a settimana, e il giro vita con lui.",
        "Se in due settimane non scende niente: togli 15 g di riso a pranzo e a cena.",
        "Se scende più di sette etti a settimana, o in palestra perdi forza: aggiungi 20 g di riso a pranzo e a cena.",
        "Conta più il metro della bilancia: se il giro vita scende e i carichi tengono, sta andando bene anche con il peso fermo."]},
    {"id": "progressione", "t": "Come progredire in palestra", "icona": "trend", "p": [
        "Ogni serie finisce quando te ne restano una o due in canna, non a sfinimento.",
        "Quando arrivi al massimo delle ripetizioni in tutte le serie, la volta dopo aumenta il carico del minimo possibile e riparti dal basso.",
        "Esempio con 8-12: 10 kg per 12, 12 e 12 ripetizioni vuol dire passare a 12 kg e ripartire da 8.",
        "Scendi sempre in 2-3 secondi: è la fase che costruisce di più.",
        "Segna i carichi nell'app: se non li segni non sai se stai migliorando.",
        "Ogni 8 settimane fai una settimana di scarico con metà delle serie."]},
    {"id": "movimento", "t": "Camminata e sonno", "icona": "walk", "p": [
        "Lavorando da casa ti muovi pochissimo: 30 minuti di camminata al giorno valgono quasi quanto la dieta, per la pancetta.",
        "Il momento più facile è dopo pranzo, oppure in chiamata con le cuffie.",
        "Dormi almeno 7 ore: dormendo poco si ha più fame e si perde più muscolo."]},
    {"id": "integratori", "t": "Integratori", "icona": "bolt", "p": [
        "Creatina: 3-5 g tutti i giorni, anche a riposo. Funziona per accumulo.",
        "Proteine in polvere: solo lo shake dopo la palestra. Il resto arriva dal cibo.",
        "Non serve altro."]},
]

# "casa": non entra nella rotazione delle schede di palestra; sta nella sezione delle attivita' libere
SCHEDE["H"] = {"n": "Circuito a casa", "fuoco": "Tutto il corpo, senza attrezzi", "casa": True, "giorno": None, "durata": 30,
               "es": [["jumping-jack", 2, "40 s", 30], ["bodyweight-squat", 3, "12-20", 60], ["push-up", 3, "8-15", 75],
                      ["reverse-lunge", 3, "10-12", 60], ["glute-bridge", 3, "12-20", 45], ["chair-dip", 3, "8-15", 60],
                      ["superman", 3, "10-15", 45], ["bicycle-crunch", 3, "16-24", 45], ["plank", 3, "30-60 s", 45]]}

CREDITI = {
    "piatti": "Foto dei piatti: Pexels, licenza libera.",
    "esercizi": "Foto degli esercizi: free-exercise-db, dominio pubblico.",
}


def macro(ricetta, tipo):
    """Totali di una ricetta per il tipo di giorno ('rest' o 'train')."""
    if ricetta.get("libero"):
        return dict(ricetta["stima"])
    i = 2 if tipo == "train" else 1
    tot = {"kcal": 0.0, "p": 0.0, "c": 0.0, "f": 0.0}
    for ing in ricetta["ing"]:
        cibo, g = CIBI[ing[0]], ing[i]
        for k in tot:
            tot[k] += cibo[k] * g / 100
    return tot


def controlla():
    for rid, r in RICETTE.items():
        for ing in r["ing"]:
            assert ing[0] in CIBI, f"{rid}: cibo sconosciuto {ing[0]}"
    for eid, e in ESERCIZI.items():
        for m in e["m1"] + e["m2"]:
            assert m in MUSCOLI, f"{eid}: muscolo sconosciuto {m}"
        for a in e["alt"]:
            assert a in ESERCIZI, f"{eid}: alternativa sconosciuta {a}"
    for sid, s in SCHEDE.items():
        for es in s["es"]:
            assert es[0] in ESERCIZI, f"scheda {sid}: esercizio sconosciuto {es[0]}"
    for elenco in (FUORI, COMUNI):
        nomi = [x[0] for x in elenco]
        assert len(nomi) == len(set(nomi)), "diario: id ripetuto"
    print(f"{'giorno':<10} {'tipo':<6} {'kcal':>6} {'P':>5} {'C':>5} {'F':>5}   scarto kcal")
    for g in SETTIMANA_TIPO:
        for momento, rid in g["pasti"].items():
            assert RICETTE[rid]["tipo"] == MOMENTI[momento]["tipo"], f"settimana tipo: {rid} non va a {momento}"
    for gruppo in GRUPPI.values():
        for c in gruppo["cibi"]:
            assert c in CIBI, f"gruppo {gruppo['n']}: cibo sconosciuto {c}"
    for i, g in enumerate(SETTIMANA):
        tot = {"kcal": 0.0, "p": 0.0, "c": 0.0, "f": 0.0}
        for momento, rid in g["pasti"].items():
            assert momento in MOMENTI and rid in RICETTE, f"{GIORNI[i]}: {momento} {rid}"
            assert RICETTE[rid]["tipo"] == MOMENTI[momento]["tipo"], f"{GIORNI[i]}: {rid} non va a {momento}"
            m = macro(RICETTE[rid], g["tipo"])
            for k in tot:
                tot[k] += m[k]
        ob = OBIETTIVI[g["tipo"]]
        print(f"{GIORNI[i]:<10} {g['tipo']:<6} {tot['kcal']:>6.0f} {tot['p']:>5.0f} {tot['c']:>5.0f} "
              f"{tot['f']:>5.0f}   {tot['kcal'] - ob['kcal']:+.0f}")
    print("\nricette (riposo | palestra):")
    for rid, r in RICETTE.items():
        a, b = macro(r, "rest"), macro(r, "train")
        print(f"  {rid:<26} {a['kcal']:>4.0f} kcal P{a['p']:>3.0f} C{a['c']:>3.0f} F{a['f']:>3.0f} | "
              f"{b['kcal']:>4.0f} kcal P{b['p']:>3.0f} C{b['c']:>3.0f} F{b['f']:>3.0f}")


def main():
    controlla()
    if "--check" in sys.argv:
        return
    versione = datetime.now().strftime("%Y%m%d-%H%M%S")
    # i video: solo quelli controllati uno per uno (tools/video.json); chi non ce l'ha resta senza
    video = {}
    for percorso in (VIDEO, VIDEO.replace("video.json", "video2.json")):
        try:
            with open(percorso, encoding="utf-8") as f:
                video.update({k: v["yt"] for k, v in json.load(f).items() if v and v.get("yt")})
        except OSError:
            pass
    for eid, e in ESERCIZI.items():
        if eid in video:
            e["video"] = video[eid]
    print(f"\nvideo: {sum(1 for e in ESERCIZI.values() if e.get('video'))} esercizi su {len(ESERCIZI)}")
    mio = {"versione": versione, "profilo": PROFILO, "obiettivi": OBIETTIVI, "settimana": SETTIMANA,
           "puntiCarenti": PUNTI_CARENTI, "guida": GUIDA}
    os.makedirs(os.path.dirname(OUT_MIO), exist_ok=True)
    with open(OUT_MIO, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(mio, ensure_ascii=False, separators=(",", ":")))
    # i piani scritti a mano per le altre persone (tools/persone.py): uno per nome utente
    persone.scrivi(PIANI, versione, CIBI, RICETTE, SETTIMANA_TIPO, ESERCIZI)
    piano = {
        "versione": versione, "obiettivi": OBIETTIVI, "cibi": CIBI, "ricette": RICETTE, "gruppi": GRUPPI,
        "momenti": MOMENTI, "giorni": GIORNI, "settimana": SETTIMANA_TIPO, "muscoli": MUSCOLI,
        "esercizi": ESERCIZI, "riscaldamento": RISCALDAMENTO, "schede": SCHEDE, "crediti": CREDITI,
        "fuori": [{"id": a, "n": b, "gr": gruppo, "kcal": k, "p": pr, "c": ca, "f": gr, "u": [uno, tanti]}
                  for a, b, gruppo, k, pr, ca, gr, uno, tanti in FUORI],
        "comuni": [dict({"id": a, "n": b, "kcal": k, "p": pr, "c": ca, "f": gr}, **({"pz": pz, "pzn": [uno, tanti]} if pz else {}))
                   for a, b, k, pr, ca, gr, pz, uno, tanti in COMUNI],
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    testo = json.dumps(piano, ensure_ascii=False, separators=(",", ":"))
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(testo)
    # la dimensione si calcola dal testo: su Google Drive quella letta dal disco arriva in ritardo
    print(f"scritti {os.path.normpath(OUT)} ({len(testo.encode('utf-8')) // 1024} KB) e {os.path.normpath(OUT_MIO)}, versione {versione}")


if __name__ == "__main__":
    main()

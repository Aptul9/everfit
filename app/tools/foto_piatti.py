#!/usr/bin/env python3
"""Mette nell'app le foto dei piatti scelte su Pexels (serve Pillow).

    python tools/foto_piatti.py <elenco delle foto scelte .json> <cartella con le foto scaricate>

L'elenco e' {"chiave": {"id": numero della foto su Pexels, "fuoco": [x, y]}}. Le foto di tutti i giorni (LOCALI)
vengono ritagliate in 4:3 attorno al fuoco e salvate in public/img/food; le altre non si scaricano: l'app le prende
dal sito di Pexels quando servono (tools/persone.py costruisce l'indirizzo dal numero). Scrive tools/foto.json,
che e' quello che leggono gli altri strumenti.
"""
import json
import os
import sys

from PIL import Image

QUI = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(QUI, "..", "public", "img", "food")
# colazioni, spuntini e il caffe': si vedono tutti i giorni, quindi stanno nell'app e ci sono anche senza rete
LOCALI = {"caffe", "yogurt-frutta", "porridge", "uova-pane", "frutta-secca", "latte-muesli", "avocado", "yogurt-bianco", "verdure-crude"}


def ritaglia(im, fuoco, w=800, h=600):
    """Il rettangolo 4:3 piu' grande che sta nella foto, centrato sul fuoco per quanto si puo'."""
    rapporto = w / h
    if im.width / im.height > rapporto:
        alto, largo = im.height, round(im.height * rapporto)
    else:
        largo, alto = im.width, round(im.width / rapporto)
    x = min(max(0, round(fuoco[0] * im.width - largo / 2)), im.width - largo)
    y = min(max(0, round(fuoco[1] * im.height - alto / 2)), im.height - alto)
    return im.crop((x, y, x + largo, y + alto)).resize((w, h), Image.LANCZOS)


def main():
    scelte = json.load(open(sys.argv[1], encoding="utf-8"))
    cartella = sys.argv[2]
    elenco, peso = {}, 0
    for chiave, voce in sorted(scelte.items()):
        if not voce:
            continue
        locale = chiave in LOCALI
        elenco[chiave] = {"id": int(voce["id"]), "locale": locale, "cosa": voce.get("cosa", "")[:120]}
        if locale:
            im = Image.open(os.path.join(cartella, chiave + ".jpg")).convert("RGB")
            fuori = os.path.join(OUT, chiave + ".jpg")
            ritaglia(im, voce.get("fuoco") or [0.5, 0.5]).save(fuori, "JPEG", quality=76, optimize=True, progressive=True)
            peso += os.path.getsize(fuori)
    with open(os.path.join(QUI, "foto.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(elenco, f, ensure_ascii=False, indent=1)
    print(len(elenco), "foto:", sum(1 for v in elenco.values() if v["locale"]), "nell'app (%d KB)," % (peso // 1024),
          sum(1 for v in elenco.values() if not v["locale"]), "prese da Pexels quando servono")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Disegna il marchio di FitFuel (la fiamma), l'icona dell'app e le schermate di avvio (serve Pillow).

    python tools/make_icons.py

Il marchio e' una fiamma con dentro una goccia: "fuel". Le curve sono scritte una volta sola, qui sotto, nello
stesso formato dei tracciati SVG (M, C, Z su una tela 100 x 100): index.html e la pagina d'accesso usano gli stessi
numeri per disegnarla a schermo, cosi' l'immagine di avvio dell'iPhone e il primo fotogramma dell'app coincidono.
"""
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter

QUI = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(QUI, "..", "public", "icons")
SFONDO = (9, 10, 13)
LIME, MENTA = (214, 255, 92), (77, 240, 160)

# larghezza e altezza in punti e densita' dello schermo di ogni iPhone: gli stessi di server/accesso.py e di index.html.
# Senza l'immagine della misura giusta, aprendo l'app dalla Home l'iPhone mostra uno schermo bianco.
IPHONE = [(320, 568, 2), (375, 667, 2), (414, 736, 3), (375, 812, 3), (414, 896, 2), (414, 896, 3), (390, 844, 3),
          (428, 926, 3), (393, 852, 3), (430, 932, 3), (402, 874, 3), (440, 956, 3), (420, 912, 3)]
SCHERMI = [(w * k, h * k) for w, h, k in IPHONE]

# La fiamma e la goccia al suo interno, su una tela 100 x 100 (gli stessi tracciati stanno in index.html).
FIAMMA = "M53 5 C55 22 78 33 78 58 C78 77 65 93 50 93 C35 93 22 78 22 61 C22 49 28 39 37 31 C38 41 42 47 48 48 C43 34 46 17 53 5 Z"
GOCCIA = "M50 84 C42 84 36.5 78 36.5 70.5 C36.5 62 44 58.5 47.5 50 C50 58 63.5 62 63.5 72.5 C63.5 79.5 57.5 84 50 84 Z"


def punti(tracciato, passi=40):
    """I punti di un tracciato fatto di M, C e Z (curve di Bezier cubiche), pronti per un poligono."""
    pezzi = tracciato.replace(",", " ").replace("M", " M ").replace("C", " C ").replace("Z", " Z ").split()
    i, penna, fuori = 0, None, []
    while i < len(pezzi):
        comando = pezzi[i]
        if comando == "M":
            penna = (float(pezzi[i + 1]), float(pezzi[i + 2]))
            fuori.append(penna)
            i += 3
        elif comando == "C":
            a, b, c = [(float(pezzi[i + 1 + 2 * k]), float(pezzi[i + 2 + 2 * k])) for k in range(3)]
            for n in range(1, passi + 1):
                t = n / passi
                u = 1 - t
                fuori.append((u ** 3 * penna[0] + 3 * u * u * t * a[0] + 3 * u * t * t * b[0] + t ** 3 * c[0],
                              u ** 3 * penna[1] + 3 * u * u * t * a[1] + 3 * u * t * t * b[1] + t ** 3 * c[1]))
            penna = c
            i += 7
        else:
            i += 1
    return fuori


def maschera(lato, tracciato, quota=1.0):
    """La sagoma del tracciato, centrata, su una tela lato x lato: `quota` e' quanto della tela occupa la tela 100 x 100."""
    S = 4
    L = lato * S
    m = Image.new("L", (L, L), 0)
    k = L * quota / 100
    sposta = (L - 100 * k) / 2
    ImageDraw.Draw(m).polygon([(sposta + x * k, sposta + y * k) for x, y in punti(tracciato)], fill=255)
    return m.resize((lato, lato), Image.LANCZOS)


def sfumatura(lato, a, b):
    """Sfumatura dall'alto (a) al basso (b), appena inclinata."""
    piccolo = Image.new("RGB", (2, 2))
    medio = tuple((x + y) // 2 for x, y in zip(a, b))
    piccolo.putdata([a, a, medio, b])
    return piccolo.resize((lato, lato), Image.BICUBIC)


def marchio(lato, quota=1.0, sfondo=SFONDO):
    """La fiamma con la goccia scavata dentro, su sfondo trasparente (RGBA)."""
    fiamma = maschera(lato, FIAMMA, quota)
    goccia = maschera(lato, GOCCIA, quota)
    img = sfumatura(lato, LIME, MENTA).convert("RGBA")
    img.putalpha(ImageChops.subtract(fiamma, goccia))
    return img


def icona(lato, quota=0.62):
    base = sfumatura(lato, (28, 32, 40), (8, 9, 12)).convert("RGBA")
    # alone di luce dietro la fiamma
    alone = Image.new("L", (lato, lato), 0)
    ImageDraw.Draw(alone).ellipse([lato * 0.2, lato * 0.28, lato * 0.8, lato * 0.92], fill=90)
    alone = alone.filter(ImageFilter.GaussianBlur(lato * 0.14))
    base = Image.composite(Image.new("RGBA", (lato, lato), (160, 255, 110, 255)), base, alone.point(lambda v: v * 0.55))
    fiamma = marchio(lato, quota)
    ombra = ImageChops.offset(fiamma.getchannel("A"), 0, int(lato * 0.025)).filter(ImageFilter.GaussianBlur(lato * 0.03))
    base = Image.composite(Image.new("RGBA", (lato, lato), (0, 0, 0, 255)), base, ombra.point(lambda v: v * 0.5))
    base.alpha_composite(fiamma)
    return base.convert("RGB")


def avvio(w, h):
    """La schermata di avvio: la fiamma al centro, larga il 34% dello schermo, come nel benvenuto di index.html."""
    tela = Image.new("RGB", (w, h), SFONDO)
    lato = int(w * 0.34)
    fiamma = marchio(lato)
    tela.paste(fiamma, ((w - lato) // 2, (h - lato) // 2), fiamma)
    return tela


def icona_pc(percorso):
    """Icona per Windows: lo stesso disegno con gli angoli tondi e la fiamma un po' piu' grande, che a 16 pixel si legga."""
    lato = 1024
    tonda = Image.new("L", (lato, lato), 0)
    ImageDraw.Draw(tonda).rounded_rectangle([0, 0, lato - 1, lato - 1], radius=int(lato * 0.225), fill=255)
    img = icona(lato, 0.72).convert("RGBA")
    img.putalpha(tonda)
    img.resize((256, 256), Image.LANCZOS).save(percorso, format="ICO", sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)])


def main():
    os.makedirs(OUT, exist_ok=True)
    pc = os.path.join(QUI, "..", "..", "desktop")
    if os.path.isdir(pc):
        icona_pc(os.path.join(pc, "fit.ico"))
    grande = icona(1024)
    for nome, lato in (("icon-512.png", 512), ("icon-192.png", 192), ("apple-touch-icon.png", 180)):
        grande.resize((lato, lato), Image.LANCZOS).save(os.path.join(OUT, nome), optimize=True)
    icona(1024, 0.5).resize((512, 512), Image.LANCZOS).save(os.path.join(OUT, "icon-maskable-512.png"), optimize=True)
    for w, h in SCHERMI:
        # pochi colori bastano (sfondo pieno e una fiamma): cosi' ogni immagine pesa una manciata di KB
        avvio(w, h).quantize(64, method=Image.MEDIANCUT).save(os.path.join(OUT, f"splash-{w}x{h}.png"), optimize=True)
    print(len(os.listdir(OUT)), "file in", os.path.normpath(OUT))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Installa o aggiorna Fit per PC e la sentinella della bilancia (Windows, Python 3.10 o piu' recente).

    python installa.py --url https://fit.esempio.it/<percorso segreto>/     la prima volta
    python installa.py                                                     per aggiornare dopo una modifica

Mette tutto in %USERPROFILE%\\dev\\fit (si cambia con --dove), crea il collegamento "FitFuel" sul desktop
e (ri)accende la sentinella, che da li' in poi parte da sola con Windows:

    venv\\              Python con bleak (Bluetooth) e pywebview (finestra)
    app\\               fit_pc.pyw, sentinella.pyw, bilancia.py, comune.py, fit.ico
    config.json        indirizzo dell'app e ultima bilancia usata
    Fit bilancia.lnk   per riaccendere la sentinella a mano
    fit.log, sentinella.log, web\\   li creano i programmi

Non in AppData: i programmi installati dallo Store ne vedono una copia tutta loro, e un'installazione
lanciata da uno di quelli non si ritroverebbe piu' aprendo l'app dal desktop. Per lo stesso motivo la
sentinella viene accesa passando da Esplora risorse: cosi' gira come se l'avessi aperta tu, e l'iscrizione
all'avvio di Windows finisce nel posto giusto.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

QUI = os.path.dirname(os.path.abspath(__file__))
FILE = ("fit_pc.pyw", "sentinella.pyw", "bilancia.py", "comune.py", "fit.ico")


def esegui(*comando):
    print(">", " ".join(comando), flush=True)
    subprocess.run(comando, check=True)


def powershell(script):
    return subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, capture_output=True, text=True).stdout.strip()


def collegamento(dove, destinazione, programma, descrizione):
    """Crea un collegamento a pythonw + programma. `destinazione` e' un'espressione PowerShell che da' il percorso del .lnk."""
    pythonw = os.path.join(dove, "venv", "Scripts", "pythonw.exe")
    app = os.path.join(dove, "app")
    ps = lambda testo: "'" + testo.replace("'", "''") + "'"
    print("collegamento:", powershell(
        f"$c = {destinazione};"
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($c);"
        f"$s.TargetPath = {ps(pythonw)};"
        f"$s.Arguments = {ps(chr(34) + os.path.join(app, programma) + chr(34))};"
        f"$s.WorkingDirectory = {ps(app)};"
        f"$s.IconLocation = {ps(os.path.join(app, 'fit.ico'))};"
        f"$s.Description = {ps(descrizione)};"
        "$s.Save(); Write-Output $c"))


def riaccendi_sentinella(dove):
    """Chiude la sentinella che gira (ha in memoria i file vecchi) e la riapre da Esplora risorse."""
    powershell("Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*sentinella.pyw*' } "
               "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    time.sleep(1)
    subprocess.run(["explorer.exe", os.path.join(dove, "Fit bilancia.lnk")])   # explorer risponde sempre 1: non e' un errore
    print("sentinella riaccesa: l'icona e' tra quelle vicino all'orologio")


def main():
    ap = argparse.ArgumentParser(description="Installa o aggiorna FitFuel per PC")
    ap.add_argument("--url", help="indirizzo completo dell'app, con il percorso segreto")
    ap.add_argument("--dove", default=os.path.join(os.path.expanduser("~"), "dev", "fit"))
    ap.add_argument("--senza-collegamento", action="store_true", help="non creare l'icona sul desktop")
    ap.add_argument("--senza-sentinella", action="store_true", help="non (ri)accendere la sentinella della bilancia")
    a = ap.parse_args()
    dove = os.path.abspath(a.dove)
    if "\\appdata\\" in dove.lower() + "\\":
        sys.exit("Scegli una cartella fuori da AppData (vedi la nota in cima a questo file).")
    config_file = os.path.join(dove, "config.json")
    config = {}
    if os.path.exists(config_file):
        with open(config_file, encoding="utf-8") as f:
            config = json.load(f)
    if a.url:
        if not a.url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            sys.exit("L'indirizzo deve cominciare con https://")
        config["url"] = a.url if a.url.endswith("/") else a.url + "/"
    if not config.get("url"):
        sys.exit("La prima volta serve l'indirizzo dell'app: python installa.py --url https://.../")

    os.makedirs(dove, exist_ok=True)
    venv = os.path.join(dove, "venv")
    python = os.path.join(venv, "Scripts", "python.exe")
    if not os.path.exists(python):
        esegui(sys.executable, "-m", "venv", venv)
    esegui(python, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--upgrade", "-r", os.path.join(QUI, "requisiti.txt"))

    app = os.path.join(dove, "app")
    os.makedirs(app, exist_ok=True)
    for nome in FILE:
        shutil.copyfile(os.path.join(QUI, nome), os.path.join(app, nome))
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=1)
    esegui(python, os.path.join(app, "bilancia.py"), "prova")
    if not a.senza_collegamento:
        # l'app prima si chiamava Fit: il collegamento vecchio prende il nome nuovo, invece di restare accanto a quello nuovo
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "$d = [Environment]::GetFolderPath('Desktop'); $v = Join-Path $d 'Fit.lnk'; $n = Join-Path $d 'FitFuel.lnk'; "
                        "if ((Test-Path $v) -and -not (Test-Path $n)) { Rename-Item $v 'FitFuel.lnk' }"], check=False)
        collegamento(dove, "Join-Path ([Environment]::GetFolderPath('Desktop')) 'FitFuel.lnk'", "fit_pc.pyw", "Dieta, allenamenti e bilancia")
    ps_dove = "'" + os.path.join(dove, "Fit bilancia.lnk").replace("'", "''") + "'"
    collegamento(dove, ps_dove, "sentinella.pyw", "Fa le pesate chieste dal telefono")
    if not a.senza_sentinella:
        riaccendi_sentinella(dove)
    print("Fatto. FitFuel e' in", dove)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Avvia il server in locale con gli account accesi, per provare accesso, persone e primo avvio.

    python tools/prova_account.py        ->  http://localhost:8766

Il capo entra con il codice 1111 2222. I dati stanno in una cartella di prova a parte (%TEMP%/fit-prova-account),
cosi' non si mescolano con quelli dell'anteprima normale. L'intelligenza artificiale, se si salva una chiave,
parla con un servizio finto in ascolto sulla porta 8799 (se c'e'), mai con quello vero.
"""
import os
import runpy
import sys
import tempfile

QUI = os.path.dirname(os.path.abspath(__file__))
os.environ.update(FIT_CODICE="11112222", FIT_COOKIE="cookie-di-prova-0123456789", FIT_NOME="Admin",
                  FIT_GEMINI_URL="http://127.0.0.1:8799/v1beta/models/%s:generateContent",
                  FIT_MISTRAL_URL="http://127.0.0.1:8799/v1/chat/completions", FIT_LOCALE_URL="http://127.0.0.1:8799")
sys.path.insert(0, os.path.join(QUI, "..", "server"))
sys.argv = ["server.py", "--root", os.path.join(QUI, "..", "public"),
            "--data", os.path.join(tempfile.gettempdir(), "fit-prova-account"), "--host", "127.0.0.1", "--port", "8766"]
runpy.run_path(os.path.join(QUI, "..", "server", "server.py"), run_name="__main__")

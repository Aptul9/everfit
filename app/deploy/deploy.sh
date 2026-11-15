#!/usr/bin/env bash
# Pubblica l'app sul server (alias ssh in FIT_SSH, predefinito fit-server; cartella /opt/fit). Da Git Bash:
#     FIT_SSH=mio-server bash deploy/deploy.sh
# Rigenera i piani e copia public e server; se e' cambiato il server controlla prima che nessuno stia usando FitAI o
# la bilancia, mette da parte una copia del database e riavvia solo fit. Alla fine confronta le impronte. Non tocca
# il compose, il reverse proxy, accesso.env ne' i dati.
#     FORZA=1 bash deploy/deploy.sh    riavvia anche se negli ultimi minuti qualcuno ha usato FitAI o la bilancia
set -euo pipefail
SSH_HOST="${FIT_SSH:-fit-server}"
cd "$(dirname "$0")/.."

# solo le impronte, senza i nomi: su Windows sha1sum li scrive in modo diverso da Linux
impronta='find public server -type f -not -path "*/__pycache__/*" -print0 | LC_ALL=C sort -z | xargs -0 sha1sum | cut -c1-40 | sha1sum | cut -c1-40'

PYTHONIOENCODING=utf-8 python tools/build_plan.py | tail -1

# (nel pezzo che gira sul server niente apostrofi: e' tutto dentro un testo tra apici)
tar -cz --exclude='__pycache__' public server | ssh "$SSH_HOST" "FORZA=${FORZA:-0}"'
  set -e
  cd /opt/fit
  rm -rf .nuovo && mkdir .nuovo && tar -xz -C .nuovo
  prima=$(sha1sum server/*.py 2>/dev/null)
  dopo=$(cd .nuovo && sha1sum server/*.py)
  if [ "$prima" != "$dopo" ] && [ "$FORZA" != 1 ]; then
    # il riavvio annulla la pesata o la domanda a FitAI in corso: se negli ultimi minuti sono stati usati, si aspetta
    in_uso=$(sudo docker logs fit --since 3m 2>&1 | grep -cE "POST /api/(chat|bilancia/richiesta)|GET /api/chat/lavoro" || true)
    if [ "$in_uso" -gt 0 ]; then
      rm -rf .nuovo
      echo "FitAI o la bilancia usati negli ultimi 3 minuti: non ho pubblicato niente. Riprova tra poco (o FORZA=1)." >&2
      exit 3
    fi
  fi
  rsync -a --delete .nuovo/public/ public/
  rsync -a --delete .nuovo/server/ server/
  rm -rf .nuovo
  if [ "$prima" != "$dopo" ]; then
    echo "riavvio per: $(diff <(echo "$prima") <(echo "$dopo") | grep "^>" | awk "{print \$3}" | tr "\n" " ")"
    # il server nuovo potrebbe cambiare la forma del database: prima se ne tiene una copia. Il database e in WAL,
    # quindi la copia la fa SQLite (un cp potrebbe perdere le ultime scritture). Pesano poco e non si cancellano da sole.
    sudo docker exec fit python -c "import sqlite3, time; d = sqlite3.connect(\"/data/fit.db.%s.copia\" % time.strftime(\"%Y%m%d-%H%M%S\")); sqlite3.connect(\"/data/fit.db\").backup(d); d.close()"
    # solo fit: nel compose ci sono anche ollama (che sta su un altro nodo) e le reti; un "up" accenderebbe un doppione qui
    sudo docker compose restart fit
    for i in $(seq 30); do
      sudo docker exec fit python -c "import urllib.request as u; u.urlopen(\"http://127.0.0.1:8080/api/health\", timeout=2)" 2>/dev/null && break
      sleep 1
    done
  fi
'

locale=$(eval "$impronta")
remota=$(ssh "$SSH_HOST" "cd /opt/fit && $impronta")
if [ "$locale" != "$remota" ]; then
  echo "ATTENZIONE: i file sul server non coincidono con quelli locali ($locale / $remota). Rilancia lo script." >&2
  exit 1
fi
ssh "$SSH_HOST" 'sudo docker ps --filter name=^fit$ --format "{{.Names}}: {{.Status}}"'
echo "Pubblicato sul server e verificato."

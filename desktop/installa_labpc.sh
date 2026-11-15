#!/usr/bin/env bash
# Installa o aggiorna su un server Linux sempre acceso (alias ssh in FIT_SSH, predefinito fit-server) la sentinella
# della bilancia. Da Git Bash, con la bilancia a portata di Bluetooth del server:
#     FIT_SSH=mio-server bash desktop/installa_labpc.sh
# - copia bilancia.py e sentinella_linux.py in /opt/fit-bilancia e il servizio in /etc/systemd/system;
# - prepara l'ambiente Python con bleak e l'utente di sistema fitbilancia;
# - accende il Bluetooth e il servizio fit-bilancia, che riparte da solo;
# - la prima volta scrive /etc/fit-bilancia/config.json con indirizzo e bilancia presi dal config del PC Windows
#   (FIT_CONFIG_PC): l'indirizzo con il percorso segreto passa da ssh e non viene mai stampato;
# - alla fine fa la prova (server e Bluetooth).
set -euo pipefail
SSH_HOST="${FIT_SSH:-fit-server}"
cd "$(dirname "$0")"
BLEAK="bleak==3.0.2"                                            # la stessa del PC Windows (requisiti.txt: >=3,<4)
CONFIG_PC="${FIT_CONFIG_PC:-$HOME/dev/fit/config.json}"

python -I bilancia.py prova >/dev/null                           # il protocollo a tavolino, prima di copiare

tar -cz bilancia.py sentinella_linux.py fit-bilancia.service | ssh "$SSH_HOST" "BLEAK=$BLEAK"'
  set -e
  tmp=$(mktemp -d) && tar -xz -C "$tmp"
  id fitbilancia >/dev/null 2>&1 || sudo useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin --groups bluetooth fitbilancia
  sudo install -d -m 755 /opt/fit-bilancia
  sudo install -m 644 "$tmp/bilancia.py" "$tmp/sentinella_linux.py" /opt/fit-bilancia/
  sudo install -m 644 "$tmp/fit-bilancia.service" /etc/systemd/system/fit-bilancia.service
  rm -rf "$tmp"
  [ -x /opt/fit-bilancia/venv/bin/python ] || sudo python3 -m venv /opt/fit-bilancia/venv
  sudo /opt/fit-bilancia/venv/bin/pip install --quiet --disable-pip-version-check "$BLEAK"
  sudo systemctl enable --now bluetooth
  sudo systemctl daemon-reload
'

if ! ssh "$SSH_HOST" 'sudo test -f /etc/fit-bilancia/config.json'; then   # la cartella e' chiusa a ubuntu: serve sudo anche per guardare
  python -I - "$CONFIG_PC" <<'EOF' | ssh "$SSH_HOST" 'sudo install -d -m 750 -g fitbilancia /etc/fit-bilancia && sudo sh -c "umask 027; cat > /etc/fit-bilancia/config.json" && sudo chgrp fitbilancia /etc/fit-bilancia/config.json'
import json
import sys
c = json.load(open(sys.argv[1], encoding="utf-8"))
print(json.dumps({"url": c["url"], "connetti": "127.0.0.1", "bilancia": c.get("bilancia")}, indent=1))
EOF
  echo "configurazione scritta (indirizzo preso dal portatile)"
fi

ssh "$SSH_HOST" 'sudo systemctl enable fit-bilancia 2>/dev/null; sudo systemctl restart fit-bilancia; sleep 4
  echo "servizio: $(systemctl is-active fit-bilancia), Bluetooth: $(systemctl is-active bluetooth)"
  sudo -u fitbilancia /opt/fit-bilancia/venv/bin/python /opt/fit-bilancia/sentinella_linux.py --prova'

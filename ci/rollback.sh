#!/usr/bin/env bash
set -euo pipefail
BASE=/opt/everfit
if test "${1:-previous}" = disable; then
  if test -L "$BASE/app"; then CURRENT=$(readlink -f "$BASE/app"); else CURRENT=$(cat "$BASE/candidate-release"); fi
  case "$CURRENT" in "$BASE"/releases/*) ;; *) exit 1 ;; esac
  export RELEASE=${CURRENT##*/}
  docker compose --project-directory "$CURRENT" --env-file "$BASE/.env" stop web app
  # Remove only the EverFit line: restoring the backup would drop routes added after it.
  grep -v '"fit.everbright.it"' /etc/sslh.cfg > "$BASE/sslh.candidate"
  install -m 644 "$BASE/sslh.candidate" /etc/sslh.cfg
  rm -f "$BASE/sslh.candidate"
  systemctl restart sslh
  systemctl is-active --quiet sslh
  echo 'EverFit disabled; data preserved'
  exit 0
fi
test -s "$BASE/previous-release"
PREVIOUS=$(cat "$BASE/previous-release")
case "$PREVIOUS" in "$BASE"/releases/*) ;; *) exit 1 ;; esac
export RELEASE=${PREVIOUS##*/}
# Images of the last three releases stay on the VM (deploy.sh): the previous tag starts as it was tested.
docker image inspect "everfit:$RELEASE" "everfit-web:$RELEASE" > /dev/null
docker compose --project-directory "$PREVIOUS" --env-file "$BASE/.env" up -d --wait --wait-timeout 120 --remove-orphans
ln -sfn "$PREVIOUS" "$BASE/app.next"
mv -Tf "$BASE/app.next" "$BASE/app"
# Database stays in place; backups taken before each deploy are in /opt/everfit/backups.
curl --fail --silent --show-error https://fit.everbright.it/api/health

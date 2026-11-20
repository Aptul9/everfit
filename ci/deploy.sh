#!/usr/bin/env bash
# Runs on the VM as root, from the release bundle CI copied to /opt/everfit. Starts the images CI built and tested
# (loaded with docker load, checked by image ID): nothing is built or pulled here.
set -euo pipefail
umask 077

BASE=/opt/everfit
DOMAIN=fit.everbright.it
OTHERS=${EVERFIT_CHECK_OTHERS-push drive servizi calendar meet teams flow}   # empty only in the CI rehearsal
KEEP_RELEASES=${EVERFIT_KEEP_RELEASES:-3}
[[ "$KEEP_RELEASES" =~ ^[0-9]+$ && "$KEEP_RELEASES" -ge 3 ]] || exit 1
RELEASE=${1:?release SHA required}
[[ "$RELEASE" =~ ^[a-f0-9]{40}$ ]] || exit 1
cd "$BASE"
test -s release.tar.gz
test -s images.tar.gz
test -s image-ids
test -s environment.new
command -v sqlite3 >/dev/null

# Shape of the secrets, without printing them: an empty path would turn "//" into an admin route.
grep -Eq '^FIT_CODICE=[A-Za-z0-9]{12,}$' environment.new
grep -Eq '^FIT_PERCORSO=[A-Za-z0-9_-]{32,}$' environment.new
data_dir=/opt/everfit/data
base_lines=2
if grep -qx 'FIT_DATA_DIR=/opt/everfit/personal-data' environment.new; then
  grep -Eq '^FIT_UTENTE=[a-z0-9][a-z0-9._-]{2,23}$' environment.new
  grep -Eq "^FIT_OWNER_HASH='pbkdf2\\\$240000\\\$[a-f0-9]{32}\\\$[a-f0-9]{64}'$" environment.new
  base_lines=5
  data_dir=/opt/everfit/personal-data
fi
# EverID (ci/everid_env.py): issuer, client id and secret together, owner e-mail and login flag optional.
everid_lines=$(grep -c '^FIT_OIDC_\|^FIT_OWNER_EMAIL=\|^FIT_LOGIN_CODICE=' environment.new || true)
if [[ $everid_lines -gt 0 ]]; then
  grep -Eq '^FIT_OIDC_ISSUER=https://[a-z0-9.-]+/application/o/[a-z0-9-]+/$' environment.new
  grep -Eq '^FIT_OIDC_CLIENT_ID=[A-Za-z0-9._~-]+$' environment.new
  grep -Eq '^FIT_OIDC_CLIENT_SECRET=[A-Za-z0-9._~-]+$' environment.new
  [[ $(grep -c '^FIT_OIDC_' environment.new) -eq 3 ]]
  [[ $(grep -c '^FIT_LOGIN_CODICE=' environment.new) -le 1 ]]
  if grep -q '^FIT_LOGIN_CODICE=' environment.new; then grep -Eq '^FIT_LOGIN_CODICE=[01]$' environment.new; fi
fi
[[ $(wc -l < environment.new) -eq $((base_lines + everid_lines)) ]]

install -d -m 700 -o 10001 -g 10001 "$data_dir"
install -d -m 700 backups bin
install -d -m 755 releases
NEXT="$BASE/releases/$RELEASE"
if [[ -e "$NEXT" || -L "$NEXT" ]]; then
  echo "Release already exists: $NEXT; refusing to replace it" >&2
  exit 1
fi
install -d -m 755 "$NEXT"
tar xzf release.tar.gz -C "$NEXT"
# shellcheck source=ci/sqlite.sh
source "$NEXT/ci/sqlite.sh"
chmod 600 environment.new

gunzip -c images.tar.gz | docker load
# image-ids holds the config digests CI read from the archive of the images it tested.
archive=$(mktemp "$BASE/.deploy-image.XXXXXXXX")
trap 'rm -f -- "$archive"' EXIT
while read -r image config; do
  docker save "$image" > "$archive"
  actual=$(tar -xOf "$archive" manifest.json | python3 "$NEXT/ci/image_config.py" | awk -v t="$image" '$1 == t { print $2 }')
  if [ "$actual" != "$config" ]; then
    echo "$image has config $actual, CI tested $config: refusing to deploy" >&2
    exit 1
  fi
  echo "$image $config matches the tested image"
done < image-ids
rm -f -- "$archive"
trap - EXIT
cp image-ids "$NEXT/image-ids"
rm -f images.tar.gz image-ids

export RELEASE
compose() { docker compose --project-directory "$NEXT" --env-file "$BASE/environment.new" "$@"; }
compose config --quiet

previous_data=/opt/everfit/data
if [[ -f .env ]] && grep -qx 'FIT_DATA_DIR=/opt/everfit/personal-data' .env; then
  previous_data=/opt/everfit/personal-data
fi
if [[ -s "$previous_data/fit.db" ]]; then
  # SQLite online backup (the database is in WAL mode: a file copy could lose the last writes).
  backup="backups/fit.db.$(date -u +%Y%m%dT%H%M%SZ).${RELEASE:0:12}"
  sqlite_snapshot "$previous_data/fit.db" "$backup"
  echo "Database backup: $BASE/$backup"
fi
# Pre-deploy copies: 14 days, never fewer than the newest three. (No glob through ls: under pipefail an empty
# backups directory would stop the first deploy.)
if [[ "${EVERFIT_KEEP_ALL_BACKUPS:-0}" != 1 ]]; then
  find backups -maxdepth 1 -name 'fit.db.*' -printf '%T@ %p\n' | sort -rn | tail -n +4 | cut -d' ' -f2- | while read -r old; do
    if [ -n "$(find "$old" -mtime +14)" ]; then rm -f "$old"; fi
  done
fi
if [[ -L app ]]; then
  readlink -f app > previous-release
  if [[ "$previous_data" != "$data_dir" ]]; then
    install -m 600 .env "$(cat previous-release)/rollback.env"
  fi
fi
printf '%s\n' "$NEXT" > candidate-release

# The SNI route must exist before Caddy asks for its first certificate (TLS-ALPN through sslh).
python3 "$NEXT/ci/routing.py" /etc/sslh.cfg "$BASE/sslh.candidate"
if ! cmp -s /etc/sslh.cfg "$BASE/sslh.candidate"; then
  if [[ "${EVERFIT_DISALLOW_ROUTING_CHANGE:-0}" == 1 ]]; then
    echo 'sslh routing changed; refusing to alter it or restart sslh' >&2
    exit 1
  fi
  if ! test -e /etc/sslh.cfg.pre-everfit; then
    cp -a /etc/sslh.cfg /etc/sslh.cfg.pre-everfit
  fi
  install -m 644 "$BASE/sslh.candidate" /etc/sslh.cfg
  # sslh has no reload: the restart drops open TLS connections of every app for a moment.
  systemctl restart sslh
  sleep 2
  systemctl is-active --quiet sslh
  echo 'sslh route added and restarted'
fi
rm -f "$BASE/sslh.candidate"

compose up -d --wait --wait-timeout 120 --remove-orphans
mv -f environment.new .env
compose() { docker compose --project-directory "$NEXT" --env-file "$BASE/.env" "$@"; }
ln -sfn "$NEXT" app.next
mv -Tf app.next app
compose ps
compose logs --tail 10 app

health=$(curl --fail --silent --show-error --retry 20 --retry-delay 6 --retry-all-errors --max-time 15 "https://$DOMAIN/api/health")
python3 -c 'import json, sys; assert json.loads(sys.argv[1]) == {"ok": True}, sys.argv[1]' "$health"
page=$(curl --silent --max-time 15 "https://$DOMAIN/")
grep -q '<title>EverFit</title>' <<< "$page"

failed=0
for name in $OTHERS; do
  code=$(curl --silent --output /dev/null --max-time 15 --write-out '%{http_code}' "https://$name.everbright.it/" || true)
  echo "$name.everbright.it $code"
  case "$code" in 2??|3??) ;; *) failed=1 ;; esac
done
test "$failed" = 0

# Nightly backup: own unit, started by the shared backup-dati.service, which stays untouched.
install -m 700 "$NEXT/ci/backup.sh" bin/backup.sh
install -m 600 "$NEXT/ci/sqlite.sh" bin/sqlite.sh
install -m 644 "$NEXT/ci/everfit-backup.service" /etc/systemd/system/everfit-backup.service
install -d -m 755 /etc/systemd/system/backup-dati.service.d
printf '[Unit]\nWants=everfit-backup.service\n' > /etc/systemd/system/backup-dati.service.d/everfit.conf
chmod 644 /etc/systemd/system/backup-dati.service.d/everfit.conf
systemctl daemon-reload
systemctl start everfit-backup.service
journalctl -u everfit-backup.service -n 1 --no-pager -o cat

# Keep the newest releases and their images; the current and previous one are always among them.
ls -1dt releases/*/ | tail -n +$((KEEP_RELEASES + 1)) | while read -r old; do
  old=${old%/}
  test "$old" = "releases/$RELEASE" && continue
  docker image rm "everfit:${old##*/}" "everfit-web:${old##*/}" >/dev/null 2>&1 || true
  rm -rf "$old"
done
rm -f release.tar.gz
echo "Deployment complete: $RELEASE"

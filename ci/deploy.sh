#!/usr/bin/env bash
# Runs on the VM as root, from the release bundle CI copied to /opt/everfit. Starts the images CI built and tested
# (loaded with docker load, checked by image ID): nothing is built or pulled here.
set -euo pipefail
umask 077

BASE=/opt/everfit
DOMAIN=fit.everbright.it
OTHERS=${EVERFIT_CHECK_OTHERS-push drive servizi calendar meet teams flow}   # empty only in the CI rehearsal
KEEP_RELEASES=3
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
test "$(wc -l < environment.new)" -eq 2

install -d -m 700 -o 10001 -g 10001 data
install -d -m 700 backups bin
install -d -m 755 releases
NEXT="$BASE/releases/$RELEASE"
rm -rf "$NEXT"
install -d -m 755 "$NEXT"
tar xzf release.tar.gz -C "$NEXT"
# shellcheck source=ci/sqlite.sh
source "$NEXT/ci/sqlite.sh"
mv -f environment.new .env
chmod 600 .env

gunzip -c images.tar.gz | docker load
# image-ids holds the config digests CI read from the archive of the images it tested.
while read -r image config; do
  actual=$(docker save "$image" | tar -xO manifest.json | python3 "$NEXT/ci/image_config.py" | awk -v t="$image" '$1 == t { print $2 }')
  if [ "$actual" != "$config" ]; then
    echo "$image has config $actual, CI tested $config: refusing to deploy" >&2
    exit 1
  fi
  echo "$image $config matches the tested image"
done < image-ids
cp image-ids "$NEXT/image-ids"
rm -f images.tar.gz image-ids

export RELEASE
compose() { docker compose --project-directory "$NEXT" --env-file "$BASE/.env" "$@"; }
compose config --quiet

if test -s data/fit.db; then
  # SQLite online backup (the database is in WAL mode: a file copy could lose the last writes).
  backup="backups/fit.db.$(date -u +%Y%m%dT%H%M%SZ).${RELEASE:0:12}"
  sqlite_snapshot data/fit.db "$backup"
  echo "Database backup: $BASE/$backup"
fi
# Pre-deploy copies: 14 days, never fewer than the newest three. (No glob through ls: under pipefail an empty
# backups directory would stop the first deploy.)
find backups -maxdepth 1 -name 'fit.db.*' -printf '%T@ %p\n' | sort -rn | tail -n +4 | cut -d' ' -f2- | while read -r old; do
  if [ -n "$(find "$old" -mtime +14)" ]; then rm -f "$old"; fi
done
if test -L app; then readlink -f app > previous-release; fi
printf '%s\n' "$NEXT" > candidate-release

# The SNI route must exist before Caddy asks for its first certificate (TLS-ALPN through sslh).
python3 "$NEXT/ci/routing.py" /etc/sslh.cfg "$BASE/sslh.candidate"
if ! cmp -s /etc/sslh.cfg "$BASE/sslh.candidate"; then
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

#!/usr/bin/env bash
# Runs on the VM as root, from the release bundle CI copied to /opt/everfit. Starts the images CI built and tested
# (loaded with docker load, checked by config digest): nothing is built or pulled here.
set -euo pipefail
umask 077

BASE=/opt/everfit
DOMAIN=fit.everbright.it
OTHERS=${EVERFIT_CHECK_OTHERS-push drive servizi calendar meet teams flow}   # empty only in the CI rehearsal
KEEP_RELEASES=3
DATA=/opt/everfit/coach
PRIVATE=/opt/everfit/private
RELEASE=${1:?release SHA required}
[[ "$RELEASE" =~ ^[a-f0-9]{40}$ ]] || exit 1
cd "$BASE"
test -s release.tar.gz
test -s images.tar.gz
test -s image-ids
test -s environment.new
command -v sqlite3 >/dev/null

# Shape of the runtime configuration, without printing it (ci/env.py wrote it from the CI secrets).
grep -Eq '^NUTRI_OIDC_ISSUER=https://[a-z0-9.-]+/application/o/[a-z0-9-]+/$' environment.new
grep -Eq '^NUTRI_OIDC_CLIENT_ID=[A-Za-z0-9._~-]+$' environment.new
grep -Eq '^NUTRI_OIDC_CLIENT_SECRET=[A-Za-z0-9._~-]+$' environment.new
grep -Eq '^NUTRI_OWNER_EMAIL=[^@[:space:]]+@[^@[:space:]]+$' environment.new
grep -qx "FIT_DATA_DIR=$DATA" environment.new
if grep -q '^NUTRI_AUTH=\|^NUTRI_SOURCE=' environment.new; then
  echo 'environment.new must not switch sign-in or the data source off' >&2
  exit 1
fi
optional=$(grep -c '^NUTRI_AGENT_MODEL=[a-z0-9.-]\+$' environment.new || true)
[[ $(wc -l < environment.new) -eq $((5 + optional)) ]]

install -d -m 700 -o 10001 -g 10001 "$DATA"
install -d -m 700 backups bin
install -d -m 755 releases
NEXT="$BASE/releases/$RELEASE"
rm -rf "$NEXT"
install -d -m 755 "$NEXT"
tar xzf release.tar.gz -C "$NEXT"
# shellcheck source=ci/sqlite.sh
source "$NEXT/ci/sqlite.sh"
chmod 600 environment.new

# Book corpus and the owner's story, from the private repository: readable by the app user only.
if test -s private.tar.gz; then
  rm -rf "$PRIVATE.next"
  install -d -m 750 -o root -g 10001 "$PRIVATE.next"
  tar xzf private.tar.gz -C "$PRIVATE.next" --no-same-owner
  chown -R root:10001 "$PRIVATE.next"
  find "$PRIVATE.next" -type d -exec chmod 750 {} + -o -type f -exec chmod 640 {} +
  test -s "$PRIVATE.next/story.md"
  test -s "$PRIVATE.next/corpus/INDEX.md"
  rm -rf "$PRIVATE"
  mv "$PRIVATE.next" "$PRIVATE"
  rm -f private.tar.gz
fi
test -d "$PRIVATE"

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
compose() { docker compose --project-directory "$NEXT" --env-file "$BASE/environment.new" "$@"; }
compose config --quiet

if [[ -s "$DATA/nutri.db" ]]; then
  # SQLite online backup (the database is in WAL mode: a file copy could lose the last writes).
  backup="backups/nutri.db.$(date -u +%Y%m%dT%H%M%SZ).${RELEASE:0:12}"
  sqlite_snapshot "$DATA/nutri.db" "$backup"
  echo "Database backup: $BASE/$backup"
fi
find backups -maxdepth 1 -name 'nutri.db.*' -printf '%T@ %p\n' | sort -rn | tail -n +4 | cut -d' ' -f2- | while read -r old; do
  if [ -n "$(find "$old" -mtime +14)" ]; then rm -f "$old"; fi
done
if [[ -L app ]]; then
  readlink -f app > previous-release
  # The release before the coach ran another application with its own environment: keep it for a rollback.
  if [[ -f .env ]] && ! grep -q '^NUTRI_OIDC_ISSUER=' .env; then
    install -m 600 .env "$(cat previous-release)/rollback.env"
  fi
fi
printf '%s\n' "$NEXT" > candidate-release

# The SNI route must exist before Caddy asks for its first certificate (TLS-ALPN through sslh).
python3 "$NEXT/ci/routing.py" /etc/sslh.cfg "$BASE/sslh.candidate"
if ! cmp -s /etc/sslh.cfg "$BASE/sslh.candidate"; then
  if ! test -e /etc/sslh.cfg.pre-everfit; then
    cp -a /etc/sslh.cfg /etc/sslh.cfg.pre-everfit
  fi
  install -m 644 "$BASE/sslh.candidate" /etc/sslh.cfg
  systemctl restart sslh
  sleep 2
  systemctl is-active --quiet sslh
  echo 'sslh route added and restarted'
fi
rm -f "$BASE/sslh.candidate"

compose up -d --wait --wait-timeout 180 --remove-orphans
mv -f environment.new .env
compose() { docker compose --project-directory "$NEXT" --env-file "$BASE/.env" "$@"; }
ln -sfn "$NEXT" app.next
mv -Tf app.next app
compose ps
compose logs --tail 10 app

health=$(curl --fail --silent --show-error --retry 20 --retry-delay 6 --retry-all-errors --max-time 15 "https://$DOMAIN/api/health")
python3 -c 'import json, sys; h = json.loads(sys.argv[1]); assert h.get("ok") is True and h.get("source") == "cronometer", h' "$health"
page=$(curl --silent --max-time 15 "https://$DOMAIN/")
grep -q '<title>EverFit</title>' <<< "$page"
links=$(curl --fail --silent --max-time 15 "https://$DOMAIN/.well-known/assetlinks.json")
grep -q 'it.alias_pv60kg.everfit' <<< "$links"
code=$(curl --silent --output /dev/null --max-time 15 --write-out '%{http_code}' "https://$DOMAIN/api/today")
test "$code" = 401

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
if [[ -s "$DATA/nutri.db" ]]; then
  systemctl start everfit-backup.service
  journalctl -u everfit-backup.service -n 1 --no-pager -o cat
fi

# Keep the newest releases and their images; the current and previous one are always among them.
ls -1dt releases/*/ | tail -n +$((KEEP_RELEASES + 1)) | while read -r old; do
  old=${old%/}
  test "$old" = "releases/$RELEASE" && continue
  test "$BASE/$old" = "$(cat previous-release 2>/dev/null || true)" && continue
  docker image rm "everfit:${old##*/}" "everfit-web:${old##*/}" >/dev/null 2>&1 || true
  rm -rf "$old"
done
rm -f release.tar.gz
echo "Deployment complete: $RELEASE"

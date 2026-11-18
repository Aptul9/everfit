#!/usr/bin/env bash
set -euo pipefail
umask 077

BASE=/opt/everfit
DOMAIN=fit.everbright.it
OTHERS="push drive servizi calendar meet teams flow"
RELEASE=${1:?release SHA required}
[[ "$RELEASE" =~ ^[a-f0-9]{40}$ ]] || exit 1
cd "$BASE"
test -s release.tar.gz
test -s environment.new

# Shape of the secrets, without printing them: an empty path would turn "//" into an admin route.
grep -Eq '^FIT_CODICE=[A-Za-z0-9]{12,}$' environment.new
grep -Eq '^FIT_PERCORSO=[A-Za-z0-9_-]{32,}$' environment.new
test "$(wc -l < environment.new)" -eq 2

install -d -m 700 -o 10001 -g 10001 data
install -d -m 700 backups
install -d -m 755 releases
NEXT="$BASE/releases/$RELEASE"
rm -rf "$NEXT"
install -d -m 755 "$NEXT"
tar xzf release.tar.gz -C "$NEXT"
chmod -R a+rX "$NEXT"
mv -f environment.new .env
chmod 600 .env
export RELEASE

compose() { docker compose --project-directory "$NEXT" --env-file "$BASE/.env" "$@"; }
compose config --quiet
compose build --pull

if test -s data/fit.db; then
  # SQLite online backup (the database is in WAL mode: a file copy could lose the last writes).
  backup="backups/fit.db.$(date -u +%Y%m%dT%H%M%SZ).${RELEASE:0:12}"
  python3 - "$BASE/data/fit.db" "$BASE/$backup" <<'PY'
import sqlite3, sys
with sqlite3.connect(sys.argv[1]) as source, sqlite3.connect(sys.argv[2]) as target:
    source.backup(target)
    assert target.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
PY
  echo "Database backup: $BASE/$backup"
  ls -1t backups/fit.db.* | tail -n +11 | xargs -r rm -f
fi
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
grep -q '"ok": true' <<< "$health"
page=$(curl --silent --max-time 15 "https://$DOMAIN/")
grep -q '<title>EverFit</title>' <<< "$page"

failed=0
for name in $OTHERS; do
  code=$(curl --silent --output /dev/null --max-time 15 --write-out '%{http_code}' "https://$name.everbright.it/" || true)
  echo "$name.everbright.it $code"
  case "$code" in 2??|3??) ;; *) failed=1 ;; esac
done
test "$failed" = 0

# Keep the last five releases and their images.
ls -1dt releases/*/ | tail -n +6 | while read -r old; do
  old=${old%/}
  test "$old" = "releases/$RELEASE" && continue
  docker image rm "everfit:${old##*/}" "everfit-web:${old##*/}" >/dev/null 2>&1 || true
  rm -rf "$old"
done
rm -f release.tar.gz
echo "Deployment complete: $RELEASE"

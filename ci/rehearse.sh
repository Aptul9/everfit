#!/usr/bin/env bash
# CI rehearsal of the production deploy on the runner: real sslh on 443 routing the SNI name to the real Caddy port,
# Python fixture then tested Rust image through docker save/load, ci/deploy.sh for both, then
# ci/rollback.sh previous and disable. Only certificate trust differs: Caddy uses its internal CA here, so curl runs
# with --insecure.
set -euo pipefail
RELEASE=${RELEASE:?}
NEXT_RELEASE=$(printf '%s' "$RELEASE" | sha1sum | cut -c1-40)
DOMAIN=fit.everbright.it
ROOT=$PWD
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

sudo DEBIAN_FRONTEND=noninteractive apt-get -qq install -y sslh sqlite3 zstd > /dev/null
sudo tee /etc/sslh.cfg > /dev/null <<'CFG'
user: "sslh";

listen:
(
    { host: "0.0.0.0"; port: "443"; }
);

protocols:
(
    { name: "ssh"; host: "127.0.0.1"; port: "22"; },
    { name: "tls"; host: "127.0.0.1"; port: "4448"; sni_hostnames: [ "push.everbright.it" ]; },
    { name: "tls"; host: "127.0.0.1"; port: "4443"; },
    { name: "anyprot"; host: "127.0.0.1"; port: "4443"; }
);
CFG
sudo cp /etc/sslh.cfg "$work/sslh.before"
echo 'DAEMON_OPTS="-F /etc/sslh.cfg"' | sudo tee /etc/default/sslh > /dev/null
sudo systemctl restart sslh
systemctl is-active --quiet sslh
echo "127.0.0.1 $DOMAIN" | sudo tee -a /etc/hosts > /dev/null

stubs="$work/bin"
mkdir "$stubs"
printf '#!/bin/sh\nexec /usr/bin/curl --insecure "$@"\n' > "$stubs/curl"
chmod +x "$stubs/curl"

ship() {   # what the deploy job copies to the VM
  local tag=$1
  sudo install -d -m 700 /opt/everfit
  docker save "everfit:$tag" "everfit-web:$tag" -o "$work/images.tar"
  tar -xOf "$work/images.tar" manifest.json | python3 ci/image_config.py > "$work/image-ids"
  gzip -c "$work/images.tar" > "$work/images.tar.gz"
  git archive --format=tar.gz HEAD docker-compose.yml ci > "$work/release.tar.gz"
  printf 'FIT_CODICE=%s\nFIT_PERCORSO=%s\n' "$FIT_CODICE" "$FIT_PERCORSO" > "$work/environment.new"
  sudo cp "$work/release.tar.gz" "$work/images.tar.gz" "$work/image-ids" "$work/environment.new" /opt/everfit/
  sudo tar xzf /opt/everfit/release.tar.gz -C /opt/everfit ci/deploy.sh
  sudo env PATH="$stubs:$PATH" FIT_TLS=internal EVERFIT_CHECK_OTHERS= bash /opt/everfit/ci/deploy.sh "$tag"
}

state() {
  curl --fail --silent --show-error --insecure "$@" "https://$DOMAIN/$FIT_PERCORSO/api/state"
}

python_state='{"di":1,"updatedAt":1,"rehearsal":"python"}'
rust_state='{"di":1,"updatedAt":2,"rehearsal":"rust"}'

echo '::group::First deploy (Python reference)'
docker build --pull -f ci/Dockerfile.python -t "everfit:$NEXT_RELEASE" .
docker tag "everfit-web:$RELEASE" "everfit-web:$NEXT_RELEASE"
ship "$NEXT_RELEASE"
echo '::endgroup::'
grep -q "\"$DOMAIN\"" /etc/sslh.cfg
python3 ci/smoke.py --url "https://$DOMAIN" --insecure
sudo test -s /etc/systemd/system/backup-dati.service.d/everfit.conf
sudo sh -c 'ls -l /var/backups/vm-dati/everfit-*.tar.zst'
state -X PUT --data-binary "$python_state" >/dev/null

echo '::group::Upgrade (tested Rust image)'
before=$(sudo sha256sum /etc/sslh.cfg)
ship "$RELEASE"
echo '::endgroup::'
test "$before" = "$(sudo sha256sum /etc/sslh.cfg)"
test "$(sudo readlink -f /opt/everfit/app)" = "/opt/everfit/releases/$RELEASE"
test "$(sudo cat /opt/everfit/previous-release)" = "/opt/everfit/releases/$NEXT_RELEASE"
backup=$(sudo find /opt/everfit/backups -name "fit.db.*.${RELEASE:0:12}" -print -quit)
test -n "$backup"
test "$(sudo sqlite3 -readonly "$backup" 'SELECT json FROM stato WHERE utente=1;')" = "$python_state"
python3 ci/smoke.py --url "https://$DOMAIN" --insecure
test "$(state)" = "$python_state"
state -X PUT --data-binary "$rust_state" >/dev/null

echo '::group::Restore a Rust-era snapshot in scratch'
sudo systemctl start everfit-backup.service
archive=$(sudo find /var/backups/vm-dati -name 'everfit-*.tar.zst' -printf '%T@ %p\n' | sort -rn | sed -n '1s/^[^ ]* //p')
sudo sha256sum -c "$archive.sha256"
mkdir "$work/restore"
sudo tar --zstd -xf "$archive" -C "$work/restore"
test "$(sudo sqlite3 -readonly "$work/restore/fit.db" 'PRAGMA integrity_check;')" = ok
test "$(sudo sqlite3 -readonly "$work/restore/fit.db" 'SELECT json FROM stato WHERE utente=1;')" = "$rust_state"
echo '::endgroup::'

echo '::group::Rollback previous'
sudo env PATH="$stubs:$PATH" FIT_TLS=internal bash ci/rollback.sh previous
echo '::endgroup::'
test "$(sudo readlink -f /opt/everfit/app)" = "/opt/everfit/releases/$NEXT_RELEASE"
python3 ci/smoke.py --url "https://$DOMAIN" --insecure
test "$(state)" = "$rust_state"

echo '::group::Rollback disable'
sudo env PATH="$stubs:$PATH" FIT_TLS=internal bash ci/rollback.sh disable
echo '::endgroup::'
sudo cmp /etc/sslh.cfg "$work/sslh.before"
if docker ps --format '{{.Names}}' | grep -q '^everfit-'; then echo 'EverFit still running after disable' >&2; exit 1; fi
cd "$ROOT"
echo 'Deploy rehearsal: PASS'

#!/usr/bin/env bash
# Reviewed manual release: called on the VM only after the user separately approves deployment.
# No session or Home-key revocation. A distinct OIDC-only rollback image and an online SQLite backup are retained.
set -euo pipefail
umask 077
BASE=/opt/everfit
fail() { printf 'Manual preflight: %s\n' "$*" >&2; exit 1; }
[[ $# == 3 ]] || fail 'expected candidate SHA, safe rollback SHA, and current live SHA'
CANDIDATE=$1
SAFE=$2
EXPECTED=$3
for sha in "$CANDIDATE" "$SAFE" "$EXPECTED"; do
  [[ "$sha" =~ ^[a-f0-9]{40}$ ]] || fail 'each release must be a 40-character SHA'
done
[[ "$CANDIDATE" != "$SAFE" && "$CANDIDATE" != "$EXPECTED" && "$SAFE" != "$EXPECTED" ]] || fail 'release SHAs must differ'
command -v flock >/dev/null || fail 'flock is required'
exec 9>"$BASE/.manual-deploy.lock"
flock -n 9 || fail 'another manual deployment is running'
STAGE="$BASE/staging/$CANDIDATE"
BACKUP="$BASE/backups/manual-$CANDIDATE"
CURRENT="$BASE/releases/$EXPECTED"
SAFE_DIR="$BASE/releases/$SAFE"
CANDIDATE_DIR="$BASE/releases/$CANDIDATE"
test "$(readlink -f "$BASE/app")" = "$CURRENT" || fail 'live release differs from the approved expectation'
test -r "$BASE/.env" && test -r "$CURRENT/ci/sqlite.sh" && test -s "$CURRENT/image-ids" || fail 'current release, environment or digest list missing'
test -d "$STAGE/candidate" && test -d "$STAGE/rollback" && test -s "$STAGE/SHA256SUMS" || fail 'bundle incomplete'
(cd "$STAGE" && sha256sum -c SHA256SUMS) || fail 'bundle checksums do not match'
[[ ! -e "$BACKUP" && ! -e "$SAFE_DIR" && ! -L "$SAFE_DIR" && ! -e "$CANDIDATE_DIR" && ! -L "$CANDIDATE_DIR" ]] || fail 'backup or target release already exists'
for path in release.tar.gz images.tar.gz image-ids environment.new; do
  [[ ! -e "$BASE/$path" && ! -L "$BASE/$path" ]] || fail "existing deploy input: $path"
done
for image in "everfit:$SAFE" "everfit-web:$SAFE" "everfit:$CANDIDATE" "everfit-web:$CANDIDATE"; do
  if docker image inspect "$image" >/dev/null 2>&1; then fail "target image tag already exists: $image"; fi
done
for key in FIT_CODICE FIT_PERCORSO FIT_OIDC_ISSUER FIT_OIDC_CLIENT_ID FIT_OIDC_CLIENT_SECRET FIT_OWNER_EMAIL; do
  grep -Eq "^${key}=.+$" "$BASE/.env" || fail "required runtime setting missing: $key"
done
grep -Eq '^FIT_OIDC_ISSUER=https://id\.everbright\.it/application/o/everfit/$' "$BASE/.env" || fail 'OIDC issuer invalid'
grep -qx 'FIT_OIDC_CLIENT_ID=everfit' "$BASE/.env" || fail 'OIDC client ID invalid'
case "$(sed -n 's/^FIT_DATA_DIR=//p' "$BASE/.env")" in
  '') DATA="$BASE/data" ;;
  "$BASE/data"|"$BASE/personal-data") DATA=$(sed -n 's/^FIT_DATA_DIR=//p' "$BASE/.env") ;;
  *) fail 'unexpected data directory' ;;
esac
test -s "$DATA/fit.db" || fail 'database missing'
for table in stato stato_storia pesate circonferenze pareri; do
  count=$(sqlite3 -batch -readonly "$DATA/fit.db" "SELECT COUNT(*) FROM pragma_table_info('$table') WHERE name='utente';")
  [[ "$count" == 1 ]] || fail "database requires an unapproved migration: $table"
done
count=$(sqlite3 -batch -readonly "$DATA/fit.db" "SELECT COUNT(*) FROM pragma_table_info('sessioni') WHERE name IN ('impronta','utente','tipo','da','creata','vista');")
[[ "$count" == 6 ]] || fail 'session schema requires an unapproved migration'
count=$(sqlite3 -batch -readonly "$DATA/fit.db" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('everid','everid_sessioni');")
[[ "$count" == 2 ]] || fail 'OIDC mapping schema missing'
count=$(sqlite3 -batch -readonly "$DATA/fit.db" 'SELECT COUNT(*) FROM utenti WHERE id=1;')
[[ "$count" == 1 ]] || fail 'owner account missing'
free_kib=$(df -Pk "$BASE" | awk 'NR==2 {print $4}')
image_bytes=0
for image in "everfit:$EXPECTED" "everfit-web:$EXPECTED"; do
  size=$(docker image inspect --format '{{.Size}}' "$image") || fail "current image unavailable: $image"
  [[ "$size" =~ ^[0-9]+$ ]] || fail "invalid image size: $image"
  image_bytes=$((image_bytes + size))
done
data_bytes=$(stat -c '%s' "$DATA/fit.db")
if [[ -f "$DATA/fit.db-wal" ]]; then data_bytes=$((data_bytes + $(stat -c '%s' "$DATA/fit.db-wal"))); fi
bundle_bytes=$(stat -c '%s' "$STAGE/candidate/images.tar.gz" "$STAGE/rollback/images.tar.gz" | awk '{n+=$1} END {printf "%.0f", n}')
needed_kib=$(((3 * (image_bytes + data_bytes + bundle_bytes) + 1023) / 1024 + 4194304))
[[ "$free_kib" =~ ^[0-9]+$ && "$free_kib" -ge "$needed_kib" ]] || fail 'insufficient space for retained images, SQLite backup and release bundles'
test "$(tar -xOf "$STAGE/rollback/release.tar.gz" ci/safe-rollback-marker)" = 'everfit-oidc-only-no-cleanup-v1' || fail 'rollback release marker missing'
for pair in "candidate:$CANDIDATE" "rollback:$SAFE"; do
  name=${pair%%:*}
  sha=${pair#*:}
  ids="$STAGE/$name/image-ids"
  [[ $(wc -l < "$ids") -eq 2 ]] || fail "$name digest list must contain exactly two images"
  grep -Eq "^everfit:${sha} sha256:[a-f0-9]{64}$" "$ids" || fail "$name app digest missing"
  grep -Eq "^everfit-web:${sha} sha256:[a-f0-9]{64}$" "$ids" || fail "$name web digest missing"
done
scratch=$(mktemp -d "$STAGE/preflight.XXXXXXXX")
tar -xzf "$STAGE/candidate/release.tar.gz" -C "$scratch" ci/deploy.sh ci/rollback.sh ci/routing.py
python3 "$scratch/ci/routing.py" /etc/sslh.cfg "$scratch/sslh.candidate"
cmp -s /etc/sslh.cfg "$scratch/sslh.candidate" || fail 'routing would change or restart sslh; no deployment attempted'

# Capture rollback inputs without printing credentials or copying them off the VM.
mkdir -m 700 "$BACKUP"
install -m 600 "$BASE/.env" "$BACKUP/environment"
printf '%s\n' "$EXPECTED" > "$BACKUP/live-release"
if [[ -f "$BASE/previous-release" ]]; then install -m 600 "$BASE/previous-release" "$BACKUP/previous-release"; fi
tar -czf "$BACKUP/live-release.tar.gz" -C "$BASE/releases" "$EXPECTED"
docker save "everfit:$EXPECTED" "everfit-web:$EXPECTED" > "$BACKUP/live-images.tar"
tar -xOf "$BACKUP/live-images.tar" manifest.json | python3 "$CURRENT/ci/image_config.py" | sort > "$BACKUP/live-image-ids"
sort "$CURRENT/image-ids" > "$BACKUP/expected-image-ids"
cmp -s "$BACKUP/live-image-ids" "$BACKUP/expected-image-ids" || fail 'current image digests differ from the retained release'
# shellcheck source=ci/sqlite.sh
source "$CURRENT/ci/sqlite.sh"
sqlite_snapshot "$DATA/fit.db" "$BACKUP/fit.db" || fail 'SQLite online backup or integrity verification failed'
backup_files=(environment live-release live-release.tar.gz live-images.tar live-image-ids fit.db)
if [[ -f "$BACKUP/previous-release" ]]; then backup_files+=(previous-release); fi
(cd "$BACKUP" && sha256sum "${backup_files[@]}" > SHA256SUMS && sha256sum -c SHA256SUMS >/dev/null)
echo "Rollback backup: $BACKUP"

# Install the independently tested safe rollback release without starting it.
mkdir -m 755 "$SAFE_DIR"
tar -xzf "$STAGE/rollback/release.tar.gz" -C "$SAFE_DIR"
gzip -dc "$STAGE/rollback/images.tar.gz" | docker load
install -m 644 "$STAGE/rollback/image-ids" "$SAFE_DIR/image-ids"
test "$(wc -l < "$SAFE_DIR/image-ids")" -eq 2 || fail 'rollback digest list must contain exactly two images'
while read -r image expected; do
  case "$image" in "everfit:$SAFE"|"everfit-web:$SAFE") ;; *) fail 'unexpected rollback image tag' ;; esac
  docker save "$image" > "$scratch/image.tar"
  actual=$(tar -xOf "$scratch/image.tar" manifest.json | python3 "$SAFE_DIR/ci/image_config.py" | awk -v t="$image" '$1 == t {print $2}')
  [[ "$actual" == "$expected" && "$expected" =~ ^sha256:[a-f0-9]{64}$ ]] || fail "rollback image digest mismatch: $image"
done < "$SAFE_DIR/image-ids"

# Run the versioned deploy script with existing configuration and without pruning retained releases or backups.
install -m 600 "$STAGE/candidate/release.tar.gz" "$BASE/release.tar.gz"
install -m 600 "$STAGE/candidate/images.tar.gz" "$BASE/images.tar.gz"
install -m 600 "$STAGE/candidate/image-ids" "$BASE/image-ids"
install -m 600 "$BACKUP/environment" "$BASE/environment.new"
EVERFIT_KEEP_RELEASES=1000000 EVERFIT_KEEP_ALL_BACKUPS=1 EVERFIT_DISALLOW_ROUTING_CHANGE=1 bash "$scratch/ci/deploy.sh" "$CANDIDATE"
cmp -s "$BACKUP/environment" "$BASE/.env" || fail 'runtime configuration changed during deployment'
printf '%s\n' "$SAFE_DIR" > "$scratch/previous-release"
chmod 600 "$scratch/previous-release"
mv -f -- "$scratch/previous-release" "$BASE/previous-release"
echo "Safe rollback release: $SAFE"
echo "Rollback script: $scratch/ci/rollback.sh"

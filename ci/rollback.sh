#!/usr/bin/env bash
set -euo pipefail
BASE=/opt/everfit
fail() { printf 'Rollback preflight: %s\n' "$*" >&2; exit 1; }

check_release() {
  local tag=${1##*/}
  [[ "$tag" =~ ^[a-f0-9]{40}$ && "$1" == "$BASE/releases/$tag" ]] ||
    fail "invalid retained release path: $1"
  test -d "$1" || fail "release directory missing: $1"
  test -r "$1/docker-compose.yml" || fail "Compose file missing or unreadable: $1/docker-compose.yml"
  test -r "$BASE/.env" || fail "runtime environment file missing or unreadable: $BASE/.env"
}

if test "${1:-previous}" = disable; then
  if test -L "$BASE/app"; then
    CURRENT=$(readlink -f "$BASE/app") || fail "cannot resolve $BASE/app"
  else
    CURRENT=$(cat "$BASE/candidate-release") || fail "cannot read $BASE/candidate-release"
  fi
  check_release "$CURRENT"
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
test "${1:-previous}" = previous || fail "unsupported operation: $1"
test -s "$BASE/previous-release" || fail "no previous release recorded in $BASE/previous-release"
PREVIOUS=$(cat "$BASE/previous-release") || fail "cannot read $BASE/previous-release"
check_release "$PREVIOUS"
export RELEASE=${PREVIOUS##*/}
test -s "$PREVIOUS/image-ids" || fail "image digest list missing or empty: $PREVIOUS/image-ids"
test -r "$PREVIOUS/ci/image_config.py" || fail "image manifest parser missing or unreadable: $PREVIOUS/ci/image_config.py"
# Use the same archive config digests as deploy.sh, including bundles from the Python releases.
for image in "everfit:$RELEASE" "everfit-web:$RELEASE"; do
  expected=$(awk -v t="$image" '$1 == t { print $2 }' "$PREVIOUS/image-ids") ||
    fail "cannot read stored config digest for $image"
  [[ "$expected" =~ ^sha256:[a-f0-9]{64}$ ]] || fail "missing, duplicate or invalid stored config digest for $image"
  actual=$(docker save "$image" | tar -xO manifest.json | python3 "$PREVIOUS/ci/image_config.py" | awk -v t="$image" '$1 == t { print $2 }') ||
    fail "cannot read archive config digest for $image"
  [[ "$actual" == "$expected" ]] || fail "$image config mismatch: expected $expected, got ${actual:-none}"
  echo "$image $actual matches the retained release"
done
runtime="$BASE/.env"
if [[ -f "$PREVIOUS/rollback.env" ]]; then runtime="$PREVIOUS/rollback.env"; fi
docker compose --project-directory "$PREVIOUS" --env-file "$runtime" config --quiet ||
  fail "invalid Compose configuration for $PREVIOUS"
docker compose --project-directory "$PREVIOUS" --env-file "$runtime" up -d --wait --wait-timeout 120 --remove-orphans
# A profile cutover has a separate volume, and keeps its former runtime configuration.
curl --fail --silent --show-error https://fit.everbright.it/api/health
if [[ "$runtime" != "$BASE/.env" ]]; then
  install -m 600 "$runtime" "$BASE/.env.next"
  mv -f "$BASE/.env.next" "$BASE/.env"
fi
ln -sfn "$PREVIOUS" "$BASE/app.next"
mv -Tf "$BASE/app.next" "$BASE/app"

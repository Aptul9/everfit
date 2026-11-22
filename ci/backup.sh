#!/usr/bin/env bash
# Nightly EverFit backup, started with backup-dati.service (03:30). The SQLite database is copied with the online
# backup API (WAL: a file copy could lose the last writes); every archive is restored to a scratch directory and
# checked before it counts.
set -euo pipefail
umask 077
DATA=/opt/everfit/coach
# shellcheck source=ci/sqlite.sh
source "$(dirname "${BASH_SOURCE[0]}")/sqlite.sh"
OUT=/var/backups/vm-dati
KEEP=14
STAMP=$(date +%Y%m%d-%H%M)
WORK=$(mktemp -d /var/tmp/everfit-backup.XXXXXX)
trap 'rm -rf "$WORK"' EXIT
install -d -m 700 "$OUT" "$WORK/snapshot" "$WORK/restore"

test -s "$DATA/nutri.db"
sqlite_snapshot "$DATA/nutri.db" "$WORK/snapshot/nutri.db"
tar -C "$DATA" --exclude='./nutri.db' --exclude='./nutri.db-wal' --exclude='./nutri.db-shm' -cf "$WORK/snapshot/files.tar" .

archive="$OUT/everfit-$STAMP.tar.zst"
tar --zstd -C "$WORK/snapshot" -cf "$archive.part" nutri.db files.tar

tar --zstd -C "$WORK/restore" -xf "$archive.part"
sqlite_verify "$WORK/restore/nutri.db"
mkdir "$WORK/restore/data"
tar -xf "$WORK/restore/files.tar" -C "$WORK/restore/data"

mv "$archive.part" "$archive"
sha256sum "$archive" | sed 's#  .*/#  #' > "$archive.sha256"
ls -1t "$OUT"/everfit-*.tar.zst | tail -n +$((KEEP + 1)) | while IFS= read -r old; do rm -f "$old" "$old.sha256"; done
echo "everfit backup: $archive $(du -h "$archive" | cut -f1), restore check ok"

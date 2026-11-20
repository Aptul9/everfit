# Session cutover

This proposal changes no live state. Any session deletion and deployment requires a separately approved plan and a current SQLite online backup. Never delete or replace user accounts, application state, measurements, notifications, or the database itself.

## Inventory

`sessioni.impronta` identifies a local session. An entry in `everid_sessioni` with the same fingerprint records an OIDC ID token; it is positive evidence that the cookie was issued by the OIDC callback. A cookie without that entry has unknown origin, not necessarily a form login. `sessioni.tipo = 'passi'` is a machine credential and is outside this cutover.

`sessioni.tipo = 'casa'` is a Home key. `sessioni.da` records the Home-key fingerprint when a cookie was created from that key. The reverse link from the original cookie to the Home key is not stored. Consequently existing Home keys cannot be reliably classified as OIDC-derived or form-derived from this schema alone.

Before a decision, count locally or against an approved read-only backup: OIDC-marked cookies, unmarked cookies, Home keys, cookies linked by `da`, and machine credentials. Report counts only, without session fingerprints, tokens, or account details.

## Options

1. Revoke unknown cookies and all Home keys, including cookies derived from those keys. Keep OIDC-marked cookies and machine credentials. This is the conservative cut: unknown users and all Home devices must authenticate again. Recreate Home keys after OIDC login. Marked OIDC cookies remain subject to group-revocation and expiry limitations; they do not prove current authorization.
2. Keep unknown Home keys until each device is independently verified. This reduces disruption but leaves a route through which a Home key originating from a form session can create another cookie. It does not complete the security cut.

## Future provenance

Record an explicit, immutable authentication source and the parent session fingerprint when issuing a Home key and every derived cookie. Future Home keys can then be preserved selectively. Do not infer this metadata retroactively from missing ID tokens, timestamps, email addresses, or account names.

## Execution and rollback

Before any approved cut, take and validate a SQLite online backup using the repository's existing snapshot procedure, with its path and checksum recorded. On an isolated copy, rehearse a transaction restricted to `sessioni` and corresponding stale `everid_sessioni` rows; verify account, state, measurements and machine-credential counts remain unchanged. After the approved live transaction, verify OIDC sign-in, machine routes, Home-key invalidation and data integrity.

Restoring session rows from a backup would also restore credentials that were intentionally revoked. Treat that as a security rollback requiring explicit approval; do not restore the whole database over newer user data. The safer recovery is fresh OIDC sign-in and new Home keys.

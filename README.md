# EverFit

Personal nutrition coach on top of [Cronometer](https://cronometer.com), built on the method of Andrea Biasci's *Project Nutrition*. Cronometer stays the food log (barcode, photos, recents); EverFit reads it, estimates the real expenditure from the weight trend, sets and corrects the targets every week, prefills each day with the usual meals in the right portions, and has a coach in the chat. Live at `https://fit.everbright.it`, behind EverID.

## How it works

- **Engine** (`backend/src/nutri/engine`): trend of the weight (Holt smoothing), adaptive expenditure (complete diary days and the weight slope, blended with the book's formula prior), daily targets per phase with guardrails, weekly check-in with capped proposals, meal plan fitting in real portions (protein first, then added fats, then carbohydrates; vegetables and locks untouched), recurring meal detection. Every number comes from here; nothing is a constant in code, every threshold is a setting with its source.
- **Server** (`backend/src/nutri`): FastAPI and SQLite. Mirrors Cronometer (diary, weigh-ins) every 30 minutes through the reverse-engineered mobile API of `cronometer-api-mcp`; writes (confirmed meals, extras, day completion) go through an outbox that retries when Cronometer is down. Web push for the Sunday check-in and the evening reminder.
- **Coach** (`backend/src/nutri/agent.py`): Claude through Meridian (the Claude subscription proxy on the VM, `127.0.0.1:3456`) or an API key. It reads with tools and runs the engine; every change it suggests is a proposal card the owner confirms.
- **Web app** (`web/`): React PWA, mobile first. **Android** (`android/`): Trusted Web Activity of the same site, published on `servizi.everbright.it/download`.

## Private data

The book corpus (`corpus/`) and the owner's story (`data/story.md`) are copyrighted or personal and never enter this public repository, its images or its artifacts. They live in the private repository named by the `PRIVATE_DATA_REPO` variable (`apps/nutritionist/`); the deploy job checks them out with the read-only deploy key `PRIVATE_DATA_KEY` and copies them straight to the VM (`/opt/everfit/private`, mounted read-only at `/private`). Without them the coach still works; the book tools answer "not found".

## CI/CD

| Workflow | What |
|---|---|
| `ci-cd.yml` | Every PR and push: deployment tests, backend tests and lint, web build, both images built and run with the production restrictions on demo data, smoke test. On `main` after a merged PR: images shipped with `docker save/load`, started by tag after their config digests match, public checks. |
| `android.yml` | APK lint and build; on `main`: signed with the existing key (installs over the old app), checked against `assetlinks.json`, published on servizi. |
| `rollback.yml` | Previous release, or disable EverFit and remove its sslh route. |

Secrets: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `PRIVATE_DATA_KEY`, `ANDROID_KEYSTORE_B64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `SERVIZI_DOWNLOAD_SSH_KEY`, `SERVIZI_HOST`, `SERVIZI_KNOWN_HOSTS`.
Variables: `OIDC_ISSUER`, `FIT_OWNER_EMAIL`, `PRIVATE_DATA_REPO`, `NUTRI_AGENT_MODEL` (optional).

`ci/env.py` turns them into the env file the VM runs with; `ci/deploy.sh` checks its shape again. Nothing is typed on the VM. The Cronometer account is connected from the app (first start, or Settings): the server checks it with a real login and keeps it encrypted (AES-GCM, key from the server secret) in its volume.

## On the VM

`/opt/everfit`: `releases/<sha>` (compose file and scripts of each release), `app` (current), `.env` (600), `coach/` (SQLite and Cronometer session, owner 10001), `private/` (corpus and story), `backups/` (pre-deploy snapshots). Caddy on `127.0.0.1:4450` behind sslh, app on `127.0.0.1:8097`, both on the host network. Nightly backup to `/var/backups/vm-dati` through `everfit-backup.service`. Data of the previous EverFit application (`data/`, `personal-data/`) is left untouched.

## Develop

```
cd backend && uv sync && uv run pytest
cd web && npm ci && npm run build
cd backend && NUTRI_SOURCE=demo NUTRI_AUTH=off uv run nutri serve     # http://127.0.0.1:8096, synthetic person
```

`NUTRI_AUTH=off` is accepted only together with the demo source.

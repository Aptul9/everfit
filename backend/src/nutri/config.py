"""Runtime configuration, from the environment only."""

import os
import secrets
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Config:
    data_dir: Path
    source: str
    tz: ZoneInfo
    secret: str
    sync_minutes: int
    web_dir: Path | None
    agent_base_url: str | None
    agent_api_key: str | None
    agent_model: str
    corpus_dir: Path
    story_path: Path
    auth: str  # "oidc" | "off" | "missing"
    public_url: str = "http://127.0.0.1:8096"
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    owner_email: str = ""

    def today(self) -> date:
        return datetime.now(self.tz).date()

    def now(self) -> datetime:
        return datetime.now(self.tz)


def _secret(data_dir: Path) -> str:
    if os.getenv("NUTRI_SECRET"):
        return os.environ["NUTRI_SECRET"]
    path = data_dir / "secret.key"
    if not path.exists():
        path.write_text(secrets.token_hex(32))
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return path.read_text().strip()


def _auth(source: str) -> str:
    """Sign-in is EverID. Turning it off is accepted only together with the demo source, so a
    misconfigured production never opens a real diary to the internet: without EverID every API
    call answers 401."""
    if os.getenv("NUTRI_AUTH") == "off":
        if source != "demo":
            raise SystemExit("NUTRI_AUTH=off is allowed only with NUTRI_SOURCE=demo")
        return "off"
    if (
        os.getenv("NUTRI_OIDC_ISSUER")
        and os.getenv("NUTRI_OIDC_CLIENT_ID")
        and os.getenv("NUTRI_OIDC_CLIENT_SECRET")
    ):
        return "oidc"
    return "missing"


def load() -> Config:
    here = Path(__file__).resolve()
    repo = here.parents[3]
    data_dir = Path(os.getenv("NUTRI_DATA_DIR", repo / "backend" / "data-local"))
    data_dir.mkdir(parents=True, exist_ok=True)
    source = os.getenv("NUTRI_SOURCE") or ("cronometer" if os.getenv("CRONOMETER_USERNAME") else "demo")
    web = os.getenv("NUTRI_WEB_DIR")
    web_dir = Path(web) if web else repo / "web" / "dist"
    private = Path(os.getenv("NUTRI_PRIVATE_DIR", repo / "private"))
    return Config(
        data_dir=data_dir,
        source=source,
        tz=ZoneInfo(os.getenv("NUTRI_TZ", "Europe/Rome")),
        secret=_secret(data_dir),
        sync_minutes=int(os.getenv("NUTRI_SYNC_MINUTES", "30")),
        web_dir=web_dir if web_dir.exists() else None,
        agent_base_url=os.getenv("ANTHROPIC_BASE_URL") or None,
        agent_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        agent_model=os.getenv("NUTRI_AGENT_MODEL", "claude-sonnet-5-5"),
        corpus_dir=Path(os.getenv("NUTRI_CORPUS_DIR", private / "corpus")),
        story_path=Path(os.getenv("NUTRI_STORY", private / "story.md")),
        auth=_auth(source),
        public_url=os.getenv("NUTRI_PUBLIC_URL", "http://127.0.0.1:8096").rstrip("/"),
        oidc_issuer=os.getenv("NUTRI_OIDC_ISSUER", ""),
        oidc_client_id=os.getenv("NUTRI_OIDC_CLIENT_ID", ""),
        oidc_client_secret=os.getenv("NUTRI_OIDC_CLIENT_SECRET", ""),
        owner_email=os.getenv("NUTRI_OWNER_EMAIL", "").strip().lower(),
    )

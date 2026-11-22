"""Read access to the corpus for the agent: index lookup, chapter pages, distilled method files."""

import re
import unicodedata
from pathlib import Path

PAGE = re.compile(r"^\[p\. (\d+)\]\s*$", re.M)
REFERENCE_DIRS = ("method", "tables", "external")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch))


class Book:
    def __init__(self, corpus: Path):
        self.corpus = corpus

    def available(self) -> bool:
        return (self.corpus / "INDEX.md").exists()

    def index(self, query: str, limit: int = 15) -> list[dict]:
        words = [w for w in _norm(query).split() if len(w) > 2]
        rows = []
        for line in (self.corpus / "INDEX.md").read_text(encoding="utf-8").splitlines():
            if not line.startswith("| ") or line.startswith("| Voce") or line.startswith("|---"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 5:
                continue
            title = _norm(cells[0])
            score = sum(1 for w in words if w in title)
            if score:
                rows.append((score, {"voce": cells[0], "pagina": int(cells[2]), "file": cells[4]}))
        rows.sort(key=lambda r: (-r[0], r[1]["pagina"]))
        return [r for _, r in rows[:limit]]

    def pages(self, file: str, first: int, last: int) -> str:
        last = min(last, first + 3)
        path = (self.corpus / file).resolve()
        if self.corpus.resolve() not in path.parents or not path.name.endswith(".md"):
            raise ValueError("file fuori dal corpus")
        text = path.read_text(encoding="utf-8")
        parts = PAGE.split(text)
        out = []
        for i in range(1, len(parts) - 1, 2):
            n = int(parts[i])
            if first <= n <= last:
                out.append(f"[p. {n}]\n{parts[i + 1].strip()}")
        if not out:
            return "Nessuna pagina in questo intervallo."
        return (
            "Testo OCR: la prosa è affidabile, i numeri no. Prima di riportare un numero cercalo in "
            "method/ o tables/.\n\n" + "\n\n".join(out)
        )

    def references(self) -> list[str]:
        return sorted(
            str(p.relative_to(self.corpus)).replace("\\", "/")
            for d in REFERENCE_DIRS
            for p in (self.corpus / d).glob("*.md")
        )

    def reference(self, name: str) -> str:
        path = (self.corpus / name).resolve()
        if not any((self.corpus / d).resolve() in path.parents for d in REFERENCE_DIRS):
            raise ValueError("si leggono solo method/, tables/ ed external/")
        return path.read_text(encoding="utf-8")

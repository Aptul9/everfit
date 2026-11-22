"""Minimal streaming client for the Anthropic Messages API.

Talks to Meridian (the local proxy serving a Claude subscription) or to the
real API with a key. The official SDK takes seconds to import; this needs
only httpx.
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx

API_VERSION = "2023-06-01"


@dataclass
class Final:
    content: list[dict] = field(default_factory=list)
    stop_reason: str | None = None


class LLMError(RuntimeError):
    pass


class Messages:
    def __init__(
        self,
        base_url: str | None,
        api_key: str | None,
        timeout: float = 120,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base = (base_url or "https://api.anthropic.com").rstrip("/")
        self.transport = transport
        self.headers = {"anthropic-version": API_VERSION, "content-type": "application/json"}
        if api_key:
            self.headers["x-api-key"] = api_key
        else:
            # Meridian: send our system prompt alone, without the Claude Code one it adds for unknown clients
            self.headers["x-meridian-agent"] = "passthrough"
        self.timeout = timeout

    async def stream(self, final: Final, **body) -> AsyncIterator[str]:
        """Yields text deltas; fills `final` with the assembled content blocks and stop reason."""
        body["stream"] = True
        blocks: dict[int, dict] = {}
        partial: dict[int, str] = {}
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            async with client.stream(
                "POST", f"{self.base}/v1/messages", headers=self.headers, json=body
            ) as resp:
                if resp.status_code >= 400:
                    raise LLMError(f"HTTP {resp.status_code}: {(await resp.aread()).decode()[:300]}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data:
                        continue
                    ev = json.loads(data)
                    t = ev.get("type")
                    if t == "content_block_start":
                        blocks[ev["index"]] = dict(ev["content_block"])
                        if blocks[ev["index"]].get("type") == "tool_use":
                            partial[ev["index"]] = ""
                    elif t == "content_block_delta":
                        d = ev["delta"]
                        b = blocks[ev["index"]]
                        if d.get("type") == "text_delta":
                            b["text"] = b.get("text", "") + d["text"]
                            yield d["text"]
                        elif d.get("type") == "input_json_delta":
                            partial[ev["index"]] += d.get("partial_json", "")
                    elif t == "content_block_stop":
                        i = ev["index"]
                        if i in partial:
                            blocks[i]["input"] = json.loads(partial.pop(i) or "{}")
                    elif t == "message_delta":
                        final.stop_reason = ev.get("delta", {}).get("stop_reason") or final.stop_reason
                    elif t == "error":
                        raise LLMError(str(ev.get("error")))
        final.content = [blocks[i] for i in sorted(blocks) if blocks[i].get("type") in ("text", "tool_use")]

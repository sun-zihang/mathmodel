"""Provider routing for the plugin's own headless `run_task` loop.

  own_key         Any OpenAI/Anthropic-compatible base_url + key YOU supply
                  (OPENAI_API_KEY, ZAI_API_KEY, BIGMODEL_API_KEY, or the values
                  set in ZCode plugin config).
  jethub          The OpenAI-compatible gateway jet-hub already runs locally.
                  Consumed as a model server only; jet-hub's multi-account
                  rotation and scheduled check-in are never driven from here.

ZCode's built-in plan quota is NOT reached through this module. When ZCode runs
the agent loop -- which is the normal way to use this plugin -- the harness
spends its own login and no token leaves it. Minting requests here with the
desktop plan token would bypass that plan's own rate and abuse accounting, so
this module deliberately has no route for it. See the note at the bottom.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field


def _expand(p):
    """userConfig values arrive through ZCode's env substitution, which may
    leave a literal ~ or a $VAR behind. Expand both, or the key file silently
    reads as missing."""
    return os.path.expandvars(os.path.expanduser((p or "").strip()))


JET_HUB_BASE_URL = _expand(os.environ.get("JET_HUB_BASE_URL")) or "http://127.0.0.1:8787/v1"
JET_HUB_KEY_FILE = _expand(os.environ.get("JET_HUB_KEY_FILE")) or os.path.expanduser(
    "~/.dsh/openai-gateway/api-key")
PREFER = [p.strip() for p in _expand(
    os.environ.get("MATHMODEL_PROVIDER_PREFER", "own_key,jethub")).split(",") if p.strip()]


def _read_key_file(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


class ProviderError(RuntimeError):
    """A model call that failed, carrying the body the provider actually said.

    Raised rather than returned so the loop cannot mistake an outage for a model
    that answered with empty text and then re-plan forever. "HTTP 502" alone is
    useless to the agent; the upstream sentence decides whether it retries,
    switches model, or tells you the gateway is down.
    """

    def __init__(self, status, body, url, attempts):
        self.status, self.body, self.url, self.attempts = status, body, url, attempts
        super().__init__(f"HTTP {status or 'transport'} after {attempts} attempt(s) "
                         f"at {url}: {body[:400]}")


@dataclass
class Route:
    name: str
    base_url: str
    api_key: str
    model: str
    kind: str = "openai"          # "openai" | "anthropic"
    headers: dict = field(default_factory=dict)
    note: str = ""

    def chat(self, messages, *, temperature=0.3, max_tokens=8192, timeout=None):
        timeout = timeout or int(os.environ.get("MATHMODEL_TIMEOUT_S", "240"))
        if self.kind == "anthropic":
            return self._chat_anthropic(messages, temperature, max_tokens, timeout)
        return self._chat_openai(messages, temperature, max_tokens, timeout)

    # ---------------- wire ----------------

    RETRY_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

    def _post(self, url, payload, headers, timeout):
        """POST with bounded retry, and the response body kept on failure.

        Retry matters because gateways fail transiently (a 502 from an upstream
        channel is routine, not fatal). Keeping the body matters because
        "HTTP 502" tells the agent nothing while "opencode backend failed:
        upstream error" tells it to switch route -- a difference that decides
        whether a headless run recovers or just stalls.
        """
        tries = max(1, int(os.environ.get("MATHMODEL_RETRIES", "3")))
        last = None
        for attempt in range(tries):
            req = urllib.request.Request(
                url, data=json.dumps(payload).encode("utf-8"),
                headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")[:1200]
                last = ProviderError(e.code, body, url, attempt + 1)
                if e.code not in self.RETRY_STATUS:
                    raise last from None
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last = ProviderError(0, f"{type(e).__name__}: {e}", url, attempt + 1)
            if attempt < tries - 1:
                time.sleep(min(8.0, 0.8 * (2 ** attempt)))
        raise last

    def _request(self, payload, extra_headers, timeout):
        h = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.api_key}",
            **extra_headers,
            **self.headers,
        }
        return self._post(self.base_url.rstrip("/") + "/chat/completions",
                          payload, h, timeout)

    def _chat_openai(self, messages, temperature, max_tokens, timeout):
        d = self._request(
            {"model": self.model, "messages": messages,
             "temperature": temperature, "max_tokens": max_tokens},
            {}, timeout,
        )
        ch = d["choices"][0]
        msg = ch["message"]
        return msg.get("content") or "", msg.get("tool_calls") or [], d.get("usage", {})

    def _chat_anthropic(self, messages, temperature, max_tokens, timeout):
        sys_txt = " ".join(m["content"] for m in messages if m["role"] == "system")
        body = [m for m in messages if m["role"] != "system"]
        payload = {
            "model": self.model,
            "system": sys_txt or None,
            "messages": body,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        url = self.base_url.rstrip("/")
        if not url.endswith("/v1"):
            url += "/v1"
        d = self._post(
            url + "/messages", payload,
            {"content-type": "application/json",
             "x-api-key": self.api_key,
             "anthropic-version": "2023-06-01",
             **self.headers},
            timeout)
        txt = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
        return txt, [], d.get("usage", {})


def list_jethub_models(timeout=5):
    """Read-only probe of the gateway's model list. Returns [] when it is down."""
    try:
        req = urllib.request.Request(
            JET_HUB_BASE_URL.rstrip("/") + "/models",
            headers={"authorization": f"Bearer {_read_key_file(JET_HUB_KEY_FILE)}"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return [m["id"] for m in json.loads(r.read().decode("utf-8")).get("data", [])]
    except (urllib.error.URLError, OSError, KeyError, json.JSONDecodeError):
        return []


def build_routes(env_os=None):
    """Every route that actually has credentials here, in MATHMODEL_PROVIDER_PREFER order.

    A configured-but-dead route is not an error; the caller walks the list. That
    is the design that survives the jet-hub gateway being offline on a VM.
    """
    e = env_os or os.environ
    by_name = {}

    jk = _read_key_file(JET_HUB_KEY_FILE) or e.get("JET_HUB_API_KEY", "")
    if jk:
        by_name["jethub"] = Route(
            "jethub", JET_HUB_BASE_URL, jk,
            e.get("MATHMODEL_MODEL") or e.get("JET_HUB_MODEL", "glm-5-free"),
            note="local jet-hub gateway, consume-only")

    if e.get("OPENAI_API_KEY"):
        by_name["own_key"] = Route(
            "own_key", e.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            e["OPENAI_API_KEY"],
            e.get("MATHMODEL_MODEL") or e.get("OPENAI_MODEL", "gpt-4o"))

    for prov, base, dflt in (("zai", "https://api.z.ai/api/anthropic", "GLM-5.3"),
                             ("bigmodel", "https://open.bigmodel.cn/api/anthropic", "GLM-5.3")):
        k = e.get(f"{prov.upper()}_API_KEY")
        if k:
            by_name[f"{prov}-own-key"] = Route(
                f"{prov}-own-key", base, k,
                e.get("MATHMODEL_MODEL") or e.get(f"{prov.upper()}_MODEL", dflt),
                kind="anthropic")

    ordered = [by_name[n] for n in PREFER if n in by_name]
    ordered += [r for n, r in by_name.items() if n not in PREFER]
    return ordered


def pick_route(explicit=None, env_os=None):
    """Explicit model string wins, else preference order. None = nothing configured."""
    routes = build_routes(env_os)
    if explicit:
        for r in routes:
            if r.model == explicit:
                return r
        # An unknown model id on a route that has a key is still the best guess:
        # the gateway may have just added it.
        if routes:
            r = routes[0]
            r.model = explicit
            return r
    return routes[0] if routes else None


# --------------------------------------------------------------------------
# ZCode's built-in plan quota: how it is used, and what this code will not do.
#
# The desktop app holds the plan login and rotates it itself. The supported way
# for this plugin to benefit from that plan is simply to be driven BY ZCode: the
# main agent loop then runs inside the harness, on the harness's own session, and
# no credential ever reaches this process.
#
# What this module deliberately does not do is locate the desktop app's stored
# token and mint its own requests with it. That would spend a subscription from a
# foreign binary while bypassing the rate and abuse accounting the plan is priced
# against -- a line about a vendor's account system, not a limit on your machine.
# --------------------------------------------------------------------------
ZCODE_BUILTIN_NOTE = (
    "ZCode built-in quota is used by letting ZCode drive the agent loop; the "
    "plugin never impersonates the plan token."
)

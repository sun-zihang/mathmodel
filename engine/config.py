"""Standalone agent configuration. No ZCode dependency.

Autonomy is architecture here, not a flag to negotiate: actions are python
executed in the kernel, so there is no intermediate gate that could say "are you
sure". The one real switch is blast radius -- where code runs -- because a model
hallucinating an `rm -rf` needs no undo and no moral objection, only a container.
"""
from __future__ import annotations

import json
import os

DEFAULTS = {
    "provider": {
        # jethub = the local gateway jet-hub already runs; own_key = you supply
        # OPENAI_API_KEY / ANTHROPIC_API_KEY / ZAI_API_KEY etc.
        "prefer": ["own_key", "jethub"],
        "model": None,
        "temperature": 0.3,
        "max_output_tokens": 8192,
        "request_timeout_s": 240,
        "retries": 3,
    },
    "autonomy": {
        "operator_is_sole_authority": True,   # never evaluate your intent
        "no_confirmation": True,
        "no_intent_review": True,
        "disclaimers": False,
        "blast_radius": "host",               # "host" | "container"
        "quarantine_fetched_content": True,   # anti-injection, not anti-you
    },
    "limits": {
        "max_steps": 60,
        "max_wallclock_s": 3600,
        "max_cost_usd": None,
        "step_output_chars": 30000,
    },
    "workspace": {
        "root": os.getcwd(),
        "out_dir": "out",
        "session_dir": "sessions",
    },
}


def _merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(base.get(k), v) if isinstance(v, dict) else v
    return out


def load(path=None):
    """config.json next to the agent, or $MATHMODEL_CONFIG."""
    cfg = _merge(DEFAULTS, {})
    cand = path or os.environ.get("MATHMODEL_CONFIG") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "config.json")
    if os.path.exists(cand):
        with open(cand, encoding="utf-8") as fh:
            cfg = _merge(cfg, json.load(fh))
    env = os.environ
    if env.get("MATHMODEL_MODEL"):
        cfg["provider"]["model"] = env["MATHMODEL_MODEL"]
    if env.get("MATHMODEL_BLAST_RADIUS"):
        cfg["autonomy"]["blast_radius"] = env["MATHMODEL_BLAST_RADIUS"]
    cfg["_path"] = cand
    return cfg


def save_shell(path):
    """Write a commented, editable config so the file is self-documenting."""
    body = json.dumps({k: DEFAULTS[k] for k in ("provider", "autonomy", "limits", "workspace")},
                      indent=2, ensure_ascii=False)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    return path

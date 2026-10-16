"""Session transcripts: every run is replayable, every number is traceable.

Not an audit of the operator. The point is that a competition report must be able
to answer "where did 190 come from" -- so every action, its output and the cost
of every step is on disk.
"""
from __future__ import annotations

import json
import os
import time


class Session:
    def __init__(self, session_dir, task="", provider="", model=""):
        self.dir = session_dir
        os.makedirs(session_dir, exist_ok=True)
        self.id = time.strftime("%Y%m%d-%H%M%S")
        self.path = os.path.join(session_dir, f"{self.id}.jsonl")
        self.started = time.time()
        self.turns = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self._write({"type": "meta", "task": task, "provider": provider,
                     "model": model, "started": self.started})

    def _write(self, rec):
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    def event(self, kind, **kw):
        self.turns += 1 if kind == "act" else 0
        self._write({"type": kind, "t": round(time.time() - self.started, 2), **kw})

    def usage(self, u):
        self.tokens_in += int(u.get("prompt_tokens") or u.get("input_tokens") or 0)
        self.tokens_out += int(u.get("completion_tokens") or u.get("output_tokens") or 0)

    def summary(self):
        return {"session": self.id, "file": self.path, "turns": self.turns,
                "wallclock_s": round(time.time() - self.started, 1),
                "tokens_in": self.tokens_in, "tokens_out": self.tokens_out}

    @staticmethod
    def replay(path):
        with open(path, encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]

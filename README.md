# mathmodel

> 中文文档见 [README.zh-CN.md](README.zh-CN.md)

Autonomous mathematical-modelling agent for [ZCode](https://zcode.z.ai/) — built for
competition work (国赛/美赛/研数模). It reads a problem, decides the decision
variables, **solves it numerically**, validates the solution, plots, and writes up.

It asks no permission and judges no intent. Not as a stance — as an architecture:
actions *are* python executed in a persistent kernel, so there is no intermediate
tool-call layer where an "are you sure?" could live. Nothing here evaluates your
motives, nothing inserts a disclaimer, and the operator's instruction is the only
authority *inside the loop*.

**That is not the same as "unlimited", and the difference is documented rather than
blurred.** See [Limits](#what-this-cannot-be-told-to-ignore) — three kinds of limit
survive any setting here, and one of them (the model's own training) cannot be
turned off from a plugin at all.

```
/solve 某零件厂用 A、B 两种原料生产甲、乙两种产品……
  -> 42 t / 16 t, 190 千元, 影子价格 u1=1（但只对前 5 吨成立）
  -> 图 + 表 + 灵敏度 + 报告，全部来自实际执行的 cell
```

---

## Install

### A. Local directory (fastest)

Point ZCode at the plugin folder. In `~/.zcode/cli/config.json`:

```json
{
  "plugins": {
    "dirs": ["/path/to/mathmodel"]
  }
}
```

That is the whole of it. A `dirs`-sourced plugin is **enabled by default**; its id
is `mathmodel@inline` (ZCode labels directory-loaded plugins with the `inline`
marketplace), so you only need an `enabledPlugins` entry to switch it *off*:

```json
{ "plugins": { "enabledPlugins": { "mathmodel@inline": false } } }
```

### B. From GitHub (a real marketplace)

This repo carries `.claude-plugin/marketplace.json`, so it can be added as a
marketplace. The key you register under becomes the `@suffix`, so the plugin id
here is `mathmodel@mathmodel`:

```json
{
  "plugins": {
    "extraKnownMarketplaces": {
      "mathmodel": { "source": { "source": "github", "repo": "sun-zihang/mathmodel" } }
    },
    "enabledPlugins": { "mathmodel@mathmodel": true }
  }
}
```

> Path B resolves the repo over plain `git`, so it needs the repository to be
> **public** (or your git credentials to already work for GitHub). On a private
> repo, use path A, or point `source` at `git` with an `https://user:token@…`
> URL that never lands in a commit.

Restart ZCode. The MCP server is spawned as `python engine/mcp_server.py`, so
`python` must be on `PATH`, and for the modelling tools:

```
pip install scipy numpy matplotlib sympy pandas
pip install pulp        # optional: integer programming via CBC
```

Nothing breaks without them — `solve_lp` falls back to a pure-python simplex,
`plot` falls back to an ASCII chart — but it tells you which fallback it took
instead of quietly giving you a different-quality answer.

---

## What you get

| Tool | What it does |
|---|---|
| `mcp__mathmodel__run_task` | Whole task headless: plan → solve → validate → plot → write up. Returns the report plus a transcript path. |
| `mcp__mathmodel__run_python` | Python in a persistent namespace (imports and variables survive between steps). |
| `mcp__mathmodel__read_file` / `write_file` | Files. Reads arrive quarantined (see below). |
| `mcp__mathmodel__shell` | Shell. |
| `mcp__mathmodel__web_fetch` | URLs, quarantined. |
| `mcp__mathmodel__list_models` | Models on the configured route. |
| `mcp__mathmodel__blast_radius` | Where code will actually execute. Read-only. |

Plus `tools_modelling`, importable inside `run_python`: `solve_lp_max`,
`shadow_price_analysis`, `newton`, `bisect`, `rk4`, `describe`, `ols`,
`pearson`, `sensitivity`, `plot`, `ascii_plot`, `table`.

**ZCode's own plan quota** is spent by ZCode driving this loop — the harness uses
its own login and no credential reaches this process. The plugin never
impersonates the plan token.

---

## Two switches

### Providers

`provider_prefer` (default `own_key,jethub`) selects from routes that actually
have credentials: your own API keys (`OPENAI_API_KEY`, `ZAI_API_KEY`,
`BIGMODEL_API_KEY` in plugin config), or a local OpenAI-compatible gateway you
already run. A route that is configured but down is not an error — the agent
walks to the next one and says which it took.

### `blast_radius`: `host` | `container`

This is the one setting with consequences, and it is the reason the plugin has a
config option at all.

- **`host`** (default) — code runs on your machine, no guard rails. Your box, your
  call. But a model that hallucinates `shutil.rmtree` will not pause to think, and
  there is no undo.
- **`container`** — `run_python` executes under `docker run` with your workspace
  bind-mounted. **If docker is missing it refuses outright** rather than running on
  the host, because a containment switch that silently degrades to "no containment"
  is worse than no switch. Enforced by a test, not by a comment.

Both are honest about what they are: a limit on *blast radius*, not on *intent*.

---

## What this cannot be told to ignore

"Zero approval" is a precise claim: **no gate in this code or in ZCode's permission
layer will pause, vet, or veto your instructions.** It is not a claim that the
agent is unlimited. Three kinds of limit survive every setting here, and pretending
otherwise would be the exact fake-completeness this repo's tests exist to catch:

**1. The model's own training — not removable from a plugin.** Every route speaks
to a hosted model (Zai's, yours, or a gateway's). If the underlying model refuses
to write malware, weapon chemistry, or similar, that refusal lives in its weights.
A harness setting cannot reach it. This is the deepest boundary in the system and
the one most likely to be misrepresented by "jailbroken agent" marketing — ours
makes no such claim.

**2. Mechanical brakes in this code, against runaway loops, not against you.**
`max_steps` (default 60), per-step timeout, 60 000-char output caps, fetch
timeouts, container `--memory/--cpus`. These exist because a hallucinating loop
will happily burn your context window, disk, or API budget forever; they are
numbers in `config.json`, all adjustable. They never ask *why* you want something.

**3. Host settings you yourself configure.** ZCode's decision order puts
`requiresUserInteraction` and `alwaysAsk` *before* the yolo bypass, and honours
`disallowedTools` / project-deny rules. This plugin declares none of those, and
ships no project ruleset — so in the default configuration none of these gates
fire. If you later add one, yours wins. That is a property of the host, not
something a plugin can promise away.

Deliberate boundaries that remain (these are design, not oversight):

**1. Prompt-injection quarantine.** Anything arriving from a webpage or a file is
wrapped in a `QUARANTINED` block and declared data, never instructions. This does
not protect you from yourself — it stops *somebody else's* webpage telling your
agent to `rm -rf ~/.ssh`. Your own instructions are never quarantined; the test
suite pins both halves of that.

**2. No third-party account systems.** The plugin consumes a local gateway as a
model server. It does not drive that gateway's account rotation, its check-in
automation, or the vendor's login it is backed by. Automating the first is a model
call; automating the second spends someone else's quota pool and trips their abuse
controls, which harms a third party and gets your accounts killed. Same line,
stated once: this is about other people's systems, not about limiting what you do
on your own machine.

---

## Tests

Six checks, all runnable, none of them decorative:

```
python tests/test_tools.py       # 35 assertions: solvers, stats, numerics, degenerate inputs
python tests/test_manifest.py    # plugin wiring: every userConfig knob is read, every path exists
python tests/test_smoke.py       # drives the MCP server exactly as ZCode does, incl. clean shutdown
python tests/test_promises.py    # the claims in this README: container refusal, quarantine, step cap
python tests/check_no_scipy.py   # pure-simplex + ASCII-plot fallbacks on a scipy-free interpreter
python tests/check_secrets.py --selftest && python tests/check_secrets.py --gate
                                 # publish gate; --selftest proves the patterns can fire at all
```

That last one exists because a scanner that only ever prints "0 matches" is
indistinguishable from a clean repo — an empty-regex bug once did exactly that
here, reporting a clean sweep while matching nothing.

`test_tools` includes the one that matters most for a report: **the pure-python
simplex and scipy must agree on the optimum *and* on the shadow prices.** They
once disagreed by a sign, which is invisible in a demo and fatal in a submission.

## Why the tooling is opinionated

`shadow_price_analysis` exists because the standard mistake in a sensitivity
section is multiplying a shadow price by a proposed change. Shadow prices are
*local* — valid until the basis changes — and competition problems are chosen so
that the naive product is wrong. On the example above: u₁ = 1 千元/吨, and +10 t is
worth **5**, not 10, because a third constraint starts binding at +5. The function
re-solves, reports the realised gain, and prints the valid interval.

Nothing in the report is allowed to be a number that was not computed. Every run
writes a JSONL transcript under `MATHMODEL_DATA_DIR/sessions/`, so "where did 190
come from" is answerable three weeks later.

## License

MIT

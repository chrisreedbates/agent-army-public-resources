# Atlas

**An open-source strategy consultant agent.** Atlas thinks like a McKinsey engagement manager: hypothesis-driven, source-traceable, opinionated, and willing to push back. It builds a structured engagement across sessions — tracker, deliverables, journal — instead of one-shot answers that get lost.

Atlas packages the reasoning core of a strategy consultant agent with pluggable transport and storage layers, so you can run it from a terminal, embed it in your own app, or wire it to Slack / Discord / a web UI of your own.

---

## What Atlas does well

- **Drives an engagement, not a Q&A.** Atlas maintains an engagement tracker — deliverable statuses, key metrics, data inventory, blockers, last session notes — so the next conversation picks up where the last one left off.
- **Bulletproof Problem Solving.** When you give Atlas a big strategic question, it disaggregates into MECE sub-problems, dispatches parallel research workers, evaluates findings against quality thresholds, and dispatches follow-up rounds when results are thin.
- **Source traceability.** Every analytical claim must trace to a source URL. Saving an analysis doc without sources triggers a warning. Hallucinated competitor pricing is the most expensive mistake a strategy agent can make, and Atlas is structurally biased against it.
- **The Obligation to Dissent.** Atlas pushes back when your assumption contradicts the data. It does not soften findings to be agreeable.

## What Atlas is not

- It is not a chatbot. It will not say "great question!" It will say "I disagree — here's the data."
- It does not generate PowerPoints out of the box. The original implementation had a deliverable-export pipeline; this OSS version drops it on purpose. The strategy docs (`engagement_tracker`, `icp`, `competitive_landscape`, `executive_brief`, …) are saved as structured JSON. Bring your own renderer.
- It is not a research-paper agent. Multi-hop research with quality gates is purpose-built for *commercial strategy*: competitive landscapes, pricing, ICP, market sizing, opportunity mapping.

---

## Install

```bash
pip install atlas-consultant
```

Or from source:

```bash
git clone https://github.com/chrisreedbates/atlas
cd atlas
pip install -e .
```

## Quick start

Atlas runs from your terminal. Install it, give it an Anthropic API key, then start a chat:

```bash
pip install atlas-consultant
export ANTHROPIC_API_KEY=<your-anthropic-api-key>
atlas chat
```

You will see a prompt:

```text
you >
```

Type the strategy question or business context you want Atlas to work through. Atlas keeps its local engagement notes and deliverables in `./atlas_state/` by default, so future sessions can pick up where you left off.

## Set up

You need an [Anthropic API key](https://console.anthropic.com/). Everything else is optional.

If you prefer a `.env` file:

```bash
cp .env.example .env
$EDITOR .env       # paste your ANTHROPIC_API_KEY
```

## Use it

### Interactive REPL

```bash
atlas chat
```

```
Atlas — an open-source strategy consultant
State directory: ./atlas_state

you > I'm thinking about raising prices 20% on our top tier. Talk me through it.
  · strategy_read: engagement_tracker
  · web_search: SaaS pricing elasticity benchmarks 2026
atlas > Don't raise 20% across the board on the top tier. Move 12% on top tier
        AND introduce a new "Enterprise" tier at 1.6x current top. Here's why:
        ...
```

State (the engagement tracker, deliverables, memory) persists between runs in `./atlas_state/`.

### Inside Codex or Claude Code

You can also use this repo as a reference prompt system inside a coding-agent session. Open the repo and ask the agent:

```text
Read src/atlas/prompts/sections.py and adopt Atlas's consulting operating model.
Act as Atlas: hypothesis-driven, source-traceable, opinionated, and willing to
push back. Use the deliverable structure in that file when saving strategy work.
```

Atlas's core behavior lives in `src/atlas/prompts/sections.py`, so coding agents can use the repo as a readable strategy-agent playbook even without running the CLI.

### One-shot research

```bash
atlas research "Map the competitive landscape for vertical CRMs in property management."
```

Atlas dispatches parallel research workers, evaluates the findings against quality thresholds (10+ competitors, 3+ sources each, ≤40% low-confidence claims), runs up to 3 rounds of follow-up research if the bar isn't met, and saves a structured `competitive_landscape` deliverable.

```bash
atlas docs                       # list saved deliverables
atlas show competitive_landscape # print the JSON
```

### As a library

```python
from atlas import Assistant

a = Assistant.from_env()
result = a.chat("Help me think through whether we should expand into LATAM.")
print(result["text"])
```

Multi-turn (you hold the history):

```python
history = []
while True:
    msg = input("> ")
    result = a.chat(msg, history=history)
    history = result["history"]
    print(result["text"])
```

### Pluggable storage

The default is filesystem JSON (`LocalStorage`). To plug in your own (Postgres, Firestore, S3, anything), implement four methods:

```python
from atlas import Assistant, Storage, Config

class MyStorage(Storage):
    def read_doc(self, key): ...
    def write_doc(self, key, doc): ...
    def list_docs(self, category=None): ...
    def read_memory(self, category="all", key=None, search=None, limit=20): ...
    def write_memory(self, category, key, title, content): ...

a = Assistant(MyStorage(), Config.from_env())
```

---

## How Atlas thinks

The consulting brain lives in [src/atlas/prompts/sections.py](src/atlas/prompts/sections.py). It's the same prompt structure that ran the original (private) deployment. Worth reading even if you don't use Atlas — it's a fairly compact codification of how to drive a strategy engagement.

Key sections:

- **Identity** — Obligation to Dissent, Pyramid Principle, no "anything else?" closers.
- **Judgment** — minimum research depth (10+ competitors, 3+ sources per claim), confidence framework (High/Medium/Low), when to ask vs. when to research vs. when to estimate.
- **Bulletproof Problem Solving** — the 7-step research framework Atlas applies to any strategic question.
- **Engagement Model** — the 8 deliverables Atlas drives toward (company_assessment, icp, competitive_landscape, pricing_positioning, opportunity_map, battlecards, market_trends, executive_brief).
- **Working Assumptions** — the pattern for handling data gaps without stopping ("Working assumption: CAC ~$800 based on rep cost / close rate. Confidence: Medium. Will refine when we have actual numbers.").
- **No Hallucinations** — every fact must trace to a source.

## Tools the model has

| Tool | What it does |
|---|---|
| `strategy_read(key)` | Load a saved deliverable. |
| `strategy_write(key, content, …)` | Save / version a deliverable. Sources required for analysis docs. |
| `strategy_list(category?)` | List saved docs. |
| `memory_read(category, key?, search?)` | Recall notes / preferences. |
| `memory_write(category, key, content)` | Save a note that persists across sessions. |
| `web_search(query)` | Search the web (Tavily → Brave → Serper → DuckDuckGo). |
| `fetch_url(url)` | Read a specific web page. |
| `start_research(problem_statement)` | Kick off the multi-worker BPS orchestrator. |

The orchestrator additionally has `dispatch_research(tasks)` to fan out parallel workers.

## Architecture

```
src/atlas/
├── prompts/         # The consulting brain — system prompts
├── tools/           # Tool handlers the LLM calls
├── storage/         # Pluggable persistence (LocalStorage = JSON on disk)
├── research/        # Multi-hop orchestrator + workers
├── assistant.py     # The chat loop
├── config.py        # Env-driven config
└── cli.py           # `atlas chat`, `atlas research`, `atlas docs`, `atlas show`
```

Everything is plain Python. No Flask, no Firestore, no Slack. Bring your own if you want them.

## Cost

A rough sense of what an Atlas session costs at Anthropic's current pricing:

- A typical chat turn: $0.01 – $0.10 depending on context size and tool calls.
- `start_research` with 5 worker tasks, 2 rounds, deep-dive on each: $0.50 – $2.00.
- Set `ATLAS_CHAT_MODEL=claude-sonnet-4-6` to cut chat costs ~5x with a meaningful quality tradeoff.

Atlas does *not* implement spend limits — it's a personal tool. If you want a hard cap, wrap `Assistant.chat()` in your own budget check.

## Contributing

Issues and PRs welcome. The interesting places to improve Atlas:

- More storage backends (Postgres, SQLite, S3, Firestore) — the interface is tiny.
- A deliverable renderer (Markdown, HTML, PDF) — Atlas saves structured JSON; turning it into pretty docs is a clean separable layer.
- Tighter quality gates in the orchestrator (citation cross-checks, recency filters).
- Front-ends — Slack/Discord/Teams/web wrappers. Atlas is intentionally transport-agnostic.

Please don't add Slack/Discord/etc. to the core package. The whole point is that the brain is portable.

## License

MIT. See [LICENSE](LICENSE).

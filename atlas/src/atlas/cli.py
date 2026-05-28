"""Command-line interface for Atlas.

Subcommands:
    atlas chat               Interactive REPL with the consultant
    atlas research "<Q>"     One-shot multi-worker research run
    atlas docs               List saved strategy documents
    atlas show <key>         Print a saved strategy document
    atlas version            Show installed version
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

from . import __version__
from .assistant import Assistant
from .config import Config
from .research.orchestrator import ResearchOrchestrator
from .storage import LocalStorage


# ----- terminal helpers -----

_IS_TTY = sys.stdout.isatty()


def _color(text: str, code: str) -> str:
    if not _IS_TTY:
        return text
    return f"\033[{code}m{text}\033[0m"


def _dim(text: str) -> str:
    return _color(text, "2")


def _bold(text: str) -> str:
    return _color(text, "1")


def _cyan(text: str) -> str:
    return _color(text, "36")


def _green(text: str) -> str:
    return _color(text, "32")


def _red(text: str) -> str:
    return _color(text, "31")


def _yellow(text: str) -> str:
    return _color(text, "33")


# ----- config + assistant construction -----


def _load_config(args) -> Config:
    config = Config.from_env()
    if getattr(args, "state_dir", None):
        config.state_dir = args.state_dir
    if getattr(args, "owner", None):
        config.owner_name = args.owner
    return config


def _load_storage(args) -> LocalStorage:
    """Storage-only loader for read-only commands. Doesn't require the API key."""
    return LocalStorage(_load_config(args).state_dir)


def _load_assistant(args) -> Assistant:
    config = _load_config(args)
    problems = config.validate()
    if problems:
        print(_red("Configuration problems:"), file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(
            "\nSet ANTHROPIC_API_KEY in your environment, or create a .env file "
            "in this directory. See .env.example for the full list.",
            file=sys.stderr,
        )
        sys.exit(2)
    storage = LocalStorage(config.state_dir)
    return Assistant(storage, config)


# ----- commands -----


def _cmd_chat(args) -> int:
    """Interactive REPL."""
    atlas = _load_assistant(args)

    print(_bold("Atlas") + _dim(" — an open-source strategy consultant"))
    print(_dim(f"State directory: {atlas.config.state_dir}"))
    print(_dim("Type your message. Ctrl-D or 'exit' to quit. Multi-line: end with a blank line."))
    print()

    history: list[dict] = []

    def on_status(msg: str) -> None:
        print(_dim(f"  [{msg}]"))

    def on_tool_call(name: str, args_in: dict) -> None:
        # Compact one-liner about the tool the model called
        if name == "web_search":
            snippet = (args_in.get("query") or "")[:60]
            print(_dim(f"  · web_search: {snippet}"))
        elif name == "fetch_url":
            snippet = (args_in.get("url") or "")[:80]
            print(_dim(f"  · fetch_url: {snippet}"))
        elif name == "start_research":
            snippet = (args_in.get("problem_statement") or "")[:80]
            print(_dim(f"  · start_research: {snippet}"))
        else:
            print(_dim(f"  · {name}"))

    while True:
        try:
            print(_bold(_cyan("you > ")), end="", flush=True)
            line = input()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if line.strip() in ("exit", "quit"):
            break
        if not line.strip():
            continue

        # Multi-line: keep reading until blank line if user ended with backslash
        if line.endswith("\\"):
            lines = [line[:-1]]
            while True:
                try:
                    nxt = input()
                except EOFError:
                    break
                if not nxt.strip():
                    break
                lines.append(nxt)
            line = "\n".join(lines)

        try:
            result = atlas.chat(
                line, history=history, on_status=on_status, on_tool_call=on_tool_call
            )
        except KeyboardInterrupt:
            print(_yellow("\n[interrupted]"))
            continue

        history = result["history"]
        print()
        print(_bold(_green("atlas >")), result["text"])
        print()

    print(_dim("Bye."))
    return 0


def _cmd_research(args) -> int:
    atlas_assistant = _load_assistant(args)
    orch = ResearchOrchestrator(
        atlas_assistant.storage,
        atlas_assistant.config,
        on_status=lambda msg: print(_dim(f"  [{msg}]")),
    )

    business_context = ""
    ctx = atlas_assistant.storage.read_doc("company_assessment")
    if ctx:
        business_context = json.dumps(ctx.get("content", {}), indent=2, default=str)

    print(_bold("Starting research:"), args.question)
    print()

    result = orch.run(args.question, business_context)
    print()
    if result.get("ok"):
        print(_green("Done."))
        print(_dim(f"  Rounds: {result.get('research_rounds')}"))
        print(_dim(f"  Deliverables saved: {', '.join(result.get('deliverables', [])) or '—'}"))
        print()
        print(_bold("Summary:"))
        print(result.get("summary", ""))
        return 0
    print(_red("Research failed:"), result.get("error", "unknown error"))
    return 1


def _cmd_docs(args) -> int:
    storage = _load_storage(args)
    docs = storage.list_docs()
    if not docs:
        print(_dim("No documents saved yet."))
        return 0
    print(_bold(f"{len(docs)} document(s):"))
    for d in docs:
        title = d.get("title") or d.get("key")
        confidence = d.get("confidence") or "—"
        version = d.get("version", 1)
        print(f"  · {_cyan(d['key']):40s} v{version}  [{confidence}]  {title}")
    return 0


def _cmd_show(args) -> int:
    storage = _load_storage(args)
    doc = storage.read_doc(args.key)
    if not doc:
        print(_red(f"No document found with key '{args.key}'"), file=sys.stderr)
        return 1
    print(json.dumps(doc, indent=2, default=str))
    return 0


def _cmd_version(args) -> int:
    print(f"atlas {__version__}")
    return 0


# ----- argparse wiring -----


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="atlas",
        description="Atlas — an open-source strategy consultant agent.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"atlas {__version__}",
        help="Show the installed version and exit.",
    )
    parser.add_argument(
        "--state-dir",
        help="Directory for Atlas state (default: $ATLAS_STATE_DIR or ./atlas_state).",
    )
    parser.add_argument(
        "--owner",
        help='Your name (Atlas addresses you by this). Default: "the user".',
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_chat = sub.add_parser("chat", help="Interactive REPL with Atlas.")
    p_chat.set_defaults(func=_cmd_chat)

    p_research = sub.add_parser("research", help="Run a one-shot multi-worker research cycle.")
    p_research.add_argument("question", help="The research question.")
    p_research.set_defaults(func=_cmd_research)

    p_docs = sub.add_parser("docs", help="List saved strategy documents.")
    p_docs.set_defaults(func=_cmd_docs)

    p_show = sub.add_parser("show", help="Print a saved strategy document.")
    p_show.add_argument("key", help="Document key (e.g. 'engagement_tracker').")
    p_show.set_defaults(func=_cmd_show)

    p_version = sub.add_parser("version", help="Show the installed version.")
    p_version.set_defaults(func=_cmd_version)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

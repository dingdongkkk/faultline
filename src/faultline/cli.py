"""Command-line adapter. Prints the same JSON the MCP tools return."""

from __future__ import annotations

import argparse
import json
import sys

from .config import ConfigError, load_config


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--repo", required=True, help="repository root")
    p.add_argument("--python", required=True, help="absolute path of the target test interpreter")
    p.add_argument("--pytest-arg", action="append", default=[], dest="pytest_args")
    p.add_argument("--declared-env", action="append", default=[])
    p.add_argument("--state-dir")
    p.add_argument("--model-endpoint", help="local llama-server, e.g. http://127.0.0.1:8089")


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw[:1] == ["agent"]:  # open-model debugging agent (local llama.cpp or Gemini API)
        from .agent import main as agent_main

        return agent_main(raw[1:])
    ap = argparse.ArgumentParser(
        prog="faultline",
        epilog="Also: faultline agent TEST --repo R --python P --provider {local,gemini}  "
               "(open-model debugging agent; see `faultline agent --help`)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    install = sub.add_parser("install-claude", help="install project-local automatic retrieval and /faultline skill")
    install.add_argument("--repo", required=True)
    install.add_argument("--mode", choices=["debug", "always"], default="debug")
    search = sub.add_parser("search", help="rank Python source and return bounded excerpts without running tests")
    _common(search)
    search.add_argument("query")
    search.add_argument("--failing-test")
    search.add_argument("--budget-tokens", type=int, default=1200)
    search.add_argument("--seen-id", action="append", default=[], dest="seen_ids")
    cap = sub.add_parser("capture", help="capture a test failure and bounded value history once")
    _common(cap)
    cap.add_argument("failing_test")
    cap.add_argument("--variable")
    cap.add_argument("--refresh", action="store_true")
    cap.add_argument("--timeout-seconds", type=int, default=60)
    cap.add_argument("--budget-tokens", type=int, default=1200)
    read = sub.add_parser("read-capture", help="page stored output without rerunning tests")
    _common(read)
    read.add_argument("capture_id")
    read.add_argument("--variable")
    read.add_argument("--section", choices=["trace", "report", "stdout", "stderr"], default="trace")
    read.add_argument("--cursor", type=int, default=0)
    read.add_argument("--budget-tokens", type=int, default=1200)
    inv = sub.add_parser("investigate")
    _common(inv)
    inv.add_argument("failing_test")
    inv.add_argument("--budget-tokens", type=int, default=1200)
    inv.add_argument("--max-rounds", type=int, default=3)
    inv.add_argument("--timeout-seconds", type=int, default=120)
    inv.add_argument("--planner", choices=["deterministic", "local-model"], default="deterministic")
    ex = sub.add_parser("expand")
    _common(ex)
    ex.add_argument("investigation_id")
    ex.add_argument("evidence_id")
    ex.add_argument("--budget-tokens", type=int, default=1000)
    ex.add_argument("--cursor")
    cp = sub.add_parser("check-patch")
    _common(cp)
    cp.add_argument("investigation_id")
    cp.add_argument("--mode", choices=["full", "affected"], default="full")
    cp.add_argument("--timeout-seconds", type=int, default=120)
    cp.add_argument("--budget-tokens", type=int, default=1500)
    sv = sub.add_parser("serve", help="run the MCP server over stdio")
    _common(sv)
    sv.add_argument("--force-planner", choices=["deterministic", "local-model"],
                    help="ignore the tool's planner argument (evaluation conditions)")
    args = ap.parse_args(argv)

    if args.cmd == "install-claude":
        from .claude import install_project
        try:
            print(json.dumps(install_project(args.repo, args.mode)))
            return 0
        except (ValueError, OSError) as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            return 2

    try:
        cfg = load_config(args.repo, args.python, pytest_args=args.pytest_args,
                          declared_env=args.declared_env, state_dir=args.state_dir,
                          model_endpoint=args.model_endpoint)
    except (ConfigError, OSError) as e:
        print(json.dumps({"error": "config", "detail": str(e)}), file=sys.stderr)
        return 2
    if args.cmd == "serve":
        try:
            from .mcp_server import serve
        except ImportError:
            print(json.dumps({"error": "missing_dependency", "detail": "pip install 'faultline[mcp]'"}),
                  file=sys.stderr)
            return 2
        serve(cfg, args.force_planner)
        return 0
    if args.cmd == "search":
        from .search import search_code

        try:
            result = search_code(cfg, args.query, args.failing_test, args.budget_tokens, args.seen_ids)
        except ValueError as e:
            print(json.dumps({"error": "invalid_argument", "detail": str(e)}), file=sys.stderr)
            return 2
        print(result.model_dump_json(exclude_none=True))
        return 0
    if args.cmd in ("capture", "read-capture"):
        from .capture import capture_failure, read_capture
        try:
            if args.cmd == "capture":
                result = capture_failure(cfg, args.failing_test, args.budget_tokens, args.timeout_seconds,
                                         args.variable, args.refresh)
            else:
                result = read_capture(cfg, args.capture_id, args.section, args.cursor, args.budget_tokens, variable=args.variable)
        except (ValueError, OSError) as e:
            print(json.dumps({"error": "capture", "detail": str(e)}), file=sys.stderr)
            return 2
        print(result.model_dump_json(exclude_none=True))
        return 0
    from .evidence import EvidenceStore

    store = EvidenceStore(cfg)
    try:
        if args.cmd == "investigate":
            from .orchestrator import investigate

            out = investigate(cfg, store, args.failing_test, args.budget_tokens, args.max_rounds,
                              args.timeout_seconds, args.planner)
        elif args.cmd == "expand":
            from .evidence import expand

            out = expand(cfg, store, args.investigation_id, args.evidence_id, args.budget_tokens, args.cursor)
        else:
            from .patch import check_patch

            out = check_patch(cfg, store, args.investigation_id, args.mode, args.timeout_seconds,
                              args.budget_tokens)
    except (KeyError, ValueError) as e:
        print(json.dumps({"error": "invalid_argument", "detail": str(e)}), file=sys.stderr)
        return 2
    print(out.model_dump_json(exclude_none=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

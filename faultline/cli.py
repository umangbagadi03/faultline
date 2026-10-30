"""
Command line entry point.

    python -m faultline.cli seed            # generate demo traces into SQLite
    python -m faultline.cli analyze         # investigate every failed trace
    python -m faultline.cli eval            # measure accuracy on labeled traces
    python -m faultline.cli import langfuse # pull failed traces from Langfuse
    python -m faultline.cli watch langfuse  # keep pulling + analyzing every N minutes
    python -m faultline.cli serve           # start API + dashboard on :8000
"""

import argparse
import json
import time

from . import config, db
from .demo.simulator import generate
from .eval import evaluate
from .graph import investigate


def cmd_seed(args):
    db.init_db()
    db.clear_all()
    traces = generate(per_scenario=args.per_scenario)
    for trace in traces:
        db.save_trace(trace)
    print(f"seeded {len(traces)} traces")


def analyze_pending(only_new: bool = False) -> int:
    done = db.autopsy_index()
    count = 0
    for trace in db.list_traces():
        if only_new and trace.id in done:
            continue
        investigate(trace)
        count += 1
    return count


def cmd_analyze(args):
    db.init_db()
    count = analyze_pending()
    print(f"analyzed {count} traces (mode={config.effective_mode()})")


def cmd_eval(args):
    db.init_db()
    mode = args.mode or config.effective_mode()
    result = evaluate(db.list_traces(), mode=mode)
    db.save_eval_run(result)
    summary = {k: v for k, v in result.items() if k not in ("per_class", "misses")}
    print(json.dumps(summary, indent=2))
    for row in result["per_class"]:
        print(f"  {row['failure_class']:<24} n={row['n']:<3} class={row['class_accuracy']:>5}%  step={row['step_accuracy']:>5}%")
    if result["misses"]:
        print("misses:")
        for miss in result["misses"]:
            print(f"  {miss['trace_id']} ({miss['scenario']}): expected {miss['expected']}, got {miss['got']}")


def import_from(source: str, limit: int) -> int:
    if source == "langfuse":
        from .adapters.langfuse import fetch_failed_traces
    elif source == "langsmith":
        from .adapters.langsmith import fetch_failed_traces
    else:
        raise SystemExit(f"unknown source {source}")
    traces = fetch_failed_traces(limit=limit)
    for trace in traces:
        db.save_trace(trace)
    return len(traces)


def cmd_import(args):
    db.init_db()
    print(f"imported {import_from(args.source, args.limit)} traces from {args.source}")


def cmd_watch(args):
    db.init_db()
    print(f"watching {args.source} every {args.every} min (Ctrl+C to stop)")
    while True:
        imported = import_from(args.source, args.limit)
        analyzed = analyze_pending(only_new=True)
        print(f"[{db.now()}] imported {imported}, analyzed {analyzed} new")
        time.sleep(args.every * 60)


def cmd_serve(args):
    import uvicorn
    uvicorn.run("faultline.api:app", host=args.host, port=args.port, reload=False)


def main():
    parser = argparse.ArgumentParser(prog="faultline")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("seed")
    p.add_argument("--per-scenario", type=int, default=3)
    p.set_defaults(func=cmd_seed)

    sub.add_parser("analyze").set_defaults(func=cmd_analyze)

    p = sub.add_parser("eval")
    p.add_argument("--mode", choices=["rules", "llm"])
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("import")
    p.add_argument("source", choices=["langfuse", "langsmith"])
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("watch")
    p.add_argument("source", choices=["langfuse", "langsmith"])
    p.add_argument("--every", type=int, default=10, help="minutes")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("serve")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

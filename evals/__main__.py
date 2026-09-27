"""CLI: ``python -m evals {cases,run,answer,agent} ...`` (see evals/README.md)."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from evals.data import LOADERS


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m evals")
    sub = parser.add_subparsers(dest="command", required=True)

    cases = sub.add_parser("cases", help="print case counts per split")
    cases.add_argument("--suite", required=True, choices=sorted(LOADERS))

    run = sub.add_parser("run", help="Level A retrieval evaluation")
    run.add_argument("--suite", required=True, choices=sorted(LOADERS))
    run.add_argument("--arms", default="bm25,bm25-paths,dense,hybrid,graphify,inquiry")
    run.add_argument("--split", default="dev", choices=["dev", "test", "all"])
    run.add_argument("--limit", type=int, help="first N cases (smoke runs only)")
    run.add_argument("--corpora", type=int, help="first N corpora (smoke runs only)")
    run.add_argument(
        "--jobs",
        type=int,
        default=3,
        help="concurrent index builds for subprocess arms",
    )
    run.add_argument(
        "--baseline",
        type=Path,
        help="earlier results file whose arms are replayed (its inquiry becomes inquiry@sha)",
    )

    answer = sub.add_parser("answer", help="Level B answer quality on LOCOMO")
    answer.add_argument("--arms", default="bm25,dense,hybrid,inquiry")
    answer.add_argument("--split", default="dev", choices=["dev", "test"])
    answer.add_argument("--n", type=int, default=200)
    answer.add_argument("--jobs", type=int, default=3)

    agent = sub.add_parser("agent", help="Level C code-agent runs per arm")
    agent.add_argument("--arms", default="floor,graphify,inquiry")
    agent.add_argument("--suites", default="swebench,erpnext")
    agent.add_argument("--split", default="test", choices=["dev", "test"])
    agent.add_argument(
        "--n", type=int, default=30, help="SWE-bench tasks (seeded order)"
    )
    agent.add_argument("--repeats", type=int, default=3)
    agent.add_argument("--model", default="claude-sonnet-5")

    sub.add_parser(
        "report", help="RFC-0003 hypothesis verdicts from the latest test runs"
    )

    args = parser.parse_args()
    if args.command == "cases":
        suite = LOADERS[args.suite]()
        print(f"{suite.name}: {len(suite.cases)} cases, dropped {suite.dropped}")
        print(dict(Counter(c.split for c in suite.cases)))
        print(f"corpora: {len({c.corpus for c in suite.cases})}")
    elif args.command == "run":
        from evals.run import run as run_suite

        run_suite(
            args.suite,
            [a for a in args.arms.split(",") if a],
            args.split,
            args.limit,
            args.corpora,
            args.jobs,
            args.baseline,
        )
    elif args.command == "answer":
        from evals.answer import run_answers

        run_answers(
            [a for a in args.arms.split(",") if a], args.split, args.n, args.jobs
        )
    elif args.command == "report":
        from evals.report import main as report_main

        report_main()
    elif args.command == "agent":
        from evals.agent import run_agents

        run_agents(
            [a for a in args.arms.split(",") if a],
            [s for s in args.suites.split(",") if s],
            args.split,
            args.n,
            args.repeats,
            args.model,
        )


if __name__ == "__main__":
    main()

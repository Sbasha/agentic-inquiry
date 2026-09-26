"""CLI: ``python -m evals {cases,run,answer,agent} ...`` (see evals/README.md)."""
from __future__ import annotations

import argparse
from collections import Counter

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
    run.add_argument("--jobs", type=int, default=3, help="concurrent index builds for subprocess arms")

    answer = sub.add_parser("answer", help="Level B answer quality on LOCOMO")
    answer.add_argument("--arms", default="bm25,dense,hybrid,inquiry")
    answer.add_argument("--split", default="dev", choices=["dev", "test"])
    answer.add_argument("--n", type=int, default=200)
    answer.add_argument("--jobs", type=int, default=3)

    args = parser.parse_args()
    if args.command == "cases":
        suite = LOADERS[args.suite]()
        print(f"{suite.name}: {len(suite.cases)} cases, dropped {suite.dropped}")
        print(dict(Counter(c.split for c in suite.cases)))
        print(f"corpora: {len({c.corpus for c in suite.cases})}")
    elif args.command == "run":
        from evals.run import run as run_suite

        run_suite(args.suite, [a for a in args.arms.split(",") if a], args.split, args.limit, args.corpora, args.jobs)
    elif args.command == "answer":
        from evals.answer import run_answers

        run_answers([a for a in args.arms.split(",") if a], args.split, args.n, args.jobs)


if __name__ == "__main__":
    main()

"""Evaluate triage against the labelled cases (tests/data/triage_cases.jsonl, #30).

    PYTHONPATH=src uv run python -m app.triage_eval          # rules only
    PYTHONPATH=src uv run python -m app.triage_eval --llm    # also rules + local LLM signals (needs OLLAMA_URL)

Reports agreement, over-triage (priority higher than expected) and under-triage (lower than expected). Under-triage of
a P1 case is the number that matters for safety. Paste the output into docs/triage.md.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .triage import PRIORITIES, triage

CASES_PATH = Path(__file__).resolve().parents[2] / "tests" / "data" / "triage_cases.jsonl"
LEVELS = list(PRIORITIES)  # P1 (most urgent) .. P4


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def evaluate(cases: list[dict], signals_for=None) -> dict:
    """Confusion matrix and error counts. signals_for(case) -> signals dict or None (rules only when omitted)."""
    matrix = {e: dict.fromkeys(LEVELS, 0) for e in LEVELS}
    misses = []
    for c in cases:
        got = triage(c, signals_for(c) if signals_for else None)
        matrix[c["expected"]][got["priority"]] += 1
        if got["priority"] != c["expected"]:
            misses.append({"id": c["id"], "expected": c["expected"], "got": got["priority"], "why": c["why"],
                           "reasons": got["reasons"]})
    rank = LEVELS.index
    return {
        "n": len(cases),
        "agree": sum(matrix[p][p] for p in LEVELS),
        "over": sum(n for e in LEVELS for g, n in matrix[e].items() if rank(g) < rank(e)),
        "under": sum(n for e in LEVELS for g, n in matrix[e].items() if rank(g) > rank(e)),
        "under_p1": sum(n for g, n in matrix["P1"].items() if g != "P1"),
        "matrix": matrix,
        "misses": misses,
    }


def report(name: str, r: dict) -> str:
    lines = [f"### {name}", "",
             f"Agreement {r['agree']}/{r['n']} ({r['agree'] / r['n']:.0%}); over-triage {r['over']}; "
             f"under-triage {r['under']}; P1 cases triaged lower: {r['under_p1']}", "",
             "| expected \\ got | " + " | ".join(LEVELS) + " |", "|---" * (len(LEVELS) + 1) + "|"]
    lines += [f"| {e} | " + " | ".join(str(r["matrix"][e][g]) for g in LEVELS) + " |" for e in LEVELS]
    if r["misses"]:
        lines += ["", "Misses:"]
        lines += [f"- `{m['id']}`: expected {m['expected']}, got {m['got']} ({m['why']}; reasons: "
                  f"{'; '.join(m['reasons'])})" for m in r["misses"]]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--llm", action="store_true", help="also evaluate rules + local LLM signals")
    args = parser.parse_args()
    cases = load_cases()
    print(report("Rules only", evaluate(cases)))
    if args.llm:
        from .triage_llm import extract_signals
        answered = 0

        def signals_for(case):
            nonlocal answered
            s = extract_signals(case.get("details") or "")
            answered += s is not None
            return s

        result = evaluate(cases, signals_for)
        print()
        print(report("Rules + local LLM", result))
        print(f"\nThe model answered {answered}/{len(cases)} cases (the others fell back to rules only).")


if __name__ == "__main__":
    main()

"""Evaluate triage against the labelled cases (tests/data/triage_cases.jsonl, #30).

    PYTHONPATH=src uv run python -m app.triage_eval          # rules only
    PYTHONPATH=src uv run python -m app.triage_eval --decider llm   # also rules + local LLM (needs OLLAMA_URL)
    TRIAGE_DECIDER=jev JEV_API_KEY=... PYTHONPATH=src uv run python -m app.triage_eval --decider jev  # hosted Jev

(--llm is kept as an alias for --decider llm.)

Reports agreement, over-triage (priority higher than expected) and under-triage (lower than expected). Under-triage of
a P1 case is the number that matters for safety. Paste the output into docs/triage.md.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .triage import PRIORITIES, explain

CASES_PATH = Path(__file__).resolve().parents[2] / "tests" / "data" / "triage_cases.jsonl"
LEVELS = list(PRIORITIES)  # P1 (most urgent) .. P4


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def evaluate(cases: list[dict], signals_for=None) -> dict:
    """Confusion matrix and error counts. signals_for(case) -> signals dict or None (rules only when omitted)."""
    matrix = {e: dict.fromkeys(LEVELS, 0) for e in LEVELS}
    misses = []
    sources: Counter = Counter()   # who answered each node: form, keyword, llm, jev
    model_p: list[tuple[float, bool]] = []   # (p of each model decision taken, did the case agree?)
    for c in cases:
        signals = signals_for(c) if signals_for else None
        got = explain(c, signals)
        sources.update(d["source"] for d in got["decisions"])
        ok = got["priority"] == c["expected"]
        for d in ((signals or {}).get("decisions") or {}).values():
            model_p.append((float(d.get("p", 0)), ok))
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
        "sources": dict(sources),
        "reliability": reliability(model_p),
    }


def reliability(model_p: list[tuple[float, bool]], width: float = 0.1) -> list[dict]:
    """Model decisions grouped by stated p, with how often their case's priority agreed with the label.

    A rough calibration check on our small set: if p means anything, higher bins should agree more often.
    """
    bins: dict[int, list[bool]] = {}
    for p, ok in model_p:
        bins.setdefault(min(int(p / width), int(1 / width) - 1), []).append(ok)
    return [{"p": f"{b * width:.1f}-{(b + 1) * width:.1f}", "n": len(v), "agree": sum(v)}
            for b, v in sorted(bins.items())]


def report(name: str, r: dict) -> str:
    lines = [f"### {name}", "",
             f"Agreement {r['agree']}/{r['n']} ({r['agree'] / r['n']:.0%}); over-triage {r['over']}; "
             f"under-triage {r['under']}; P1 cases triaged lower: {r['under_p1']}", "",
             "| expected \\ got | " + " | ".join(LEVELS) + " |", "|---" * (len(LEVELS) + 1) + "|"]
    lines += [f"| {e} | " + " | ".join(str(r["matrix"][e][g]) for g in LEVELS) + " |" for e in LEVELS]
    if r.get("sources"):
        lines += ["", "Answered by: " + ", ".join(f"{k} {v}" for k, v in sorted(r["sources"].items()))]
    if r.get("reliability"):
        lines += ["", "| model p | decisions | case agreed |", "|---|---|---|"]
        lines += [f"| {b['p']} | {b['n']} | {b['agree']}/{b['n']} |" for b in r["reliability"]]
    if r["misses"]:
        lines += ["", "Misses:"]
        lines += [f"- `{m['id']}`: expected {m['expected']}, got {m['got']} ({m['why']}; reasons: "
                  f"{'; '.join(m['reasons'])})" for m in r["misses"]]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--decider", choices=["rules", "llm", "jev"], default="rules",
                        help="also evaluate rules + this model decider (llm: local Ollama; jev: hosted System One)")
    parser.add_argument("--llm", action="store_true", help="same as --decider llm")
    args = parser.parse_args()
    decider = "llm" if args.llm else args.decider
    cases = load_cases()
    print(report("Rules only", evaluate(cases)))
    if decider != "rules":
        from . import config
        from .triage_llm import extract_signals
        config.TRIAGE_DECIDER = "jev" if decider == "jev" else "ollama"
        answered = 0

        def signals_for(case):
            nonlocal answered
            s = extract_signals(case.get("details") or "", case.get("form"))
            answered += s is not None
            return s

        result = evaluate(cases, signals_for)
        name = "Rules + Jev (System One)" if decider == "jev" else "Rules + local LLM"
        print()
        print(report(name, result))
        print(f"\nThe model answered {answered}/{len(cases)} cases (the others fell back to rules only).")


if __name__ == "__main__":
    main()

# Hack for Impact

Hackathon project (NVIDIA Hack for Impact Sheffield, 13 Nov 2026): an agentic AI system running on local compute, aimed at one of the Economic Systems, Public Services or Urban Operations tracks. See `docs/challenge.md` for the brief and judging criteria (impact, technical execution, feasibility).

## Layout
- `src/`: application and agent code
- `data/`: local datasets, git-ignored except `data/README.md` and `data/sample/`. Record provenance there.
- `docs/`: brief, design notes, pitch material

## Conventions
- Time is short: prefer working end-to-end demos over polish.
- Prefer local inference over hosted APIs where practical, since local compute is a judging criterion.
- Never commit secrets or raw datasets.
- Update the "Chosen track and idea" and "Getting started" sections of `README.md` once decided.

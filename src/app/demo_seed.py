"""Fill the triage dashboard with a realistic mix of reports for the live demo and the pitch video (#30).

    PYTHONPATH=src uv run python -m app.demo_seed            # add the demo reports
    PYTHONPATH=src uv run python -m app.demo_seed --reset    # remove earlier demo reports first

Reports go through the real filing code (tools.file_report / file_tree_report), so they get geocoding, triage and
any LLM or map-context signals exactly as a live report would. Each seeded record is marked "seed": true and
backdated by its scenario's age, so a repeat-report cluster spans several days. --reset removes only seeded records
from config.REPORTS_PATH; real reports are kept.

Locations are real Sheffield streets with fixed coordinates (no geocoding needed). The repeat-report pothole sits at
the FixMyStreet sample's "repeatedly reported" pothole (data/sample_sheffield_issues.json).
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from . import config, tools

# (age in hours, filing function, kwargs). Expected priority with the rules alone is noted on each.
SCENARIOS = [
    # P1: Category 1 pothole on a main road, and someone has already been hurt.
    (2, "file_report", dict(surface="road", depth_band="Greater than 40mm", location="Ecclesall Road, Sheffield S11 8HW",
                            description="Very deep pothole in the inbound lane by the bus stop. A cyclist came off on it this morning.",
                            lat=53.370045, lon=-1.494873)),
    # P1: fallen street tree across the road.
    (1, "file_tree_report", dict(tree_location="Highway", problem="Fallen", blocking=True,
                                 location="Rustlings Road, Sheffield S11 7AA",
                                 description="Big branch has come down in the wind and is blocking the road. Cars are turning round.",
                                 lat=53.366512, lon=-1.506120)),
    # P2: dangerous tree, not yet in the way.
    (20, "file_tree_report", dict(tree_location="Highway", problem="Dangerous", blocking=False,
                                  location="Kenwood Park Road, Sheffield S7 1NF",
                                  description="Large tree leaning badly towards the pavement with a split in the trunk.",
                                  lat=53.358950, lon=-1.487780)),
    # P2: shallow pothole, but outside a school on a bus route.
    (6, "file_report", dict(surface="pavement", depth_band="Less than 20mm", location="Abbeydale Road, Sheffield S7 1FD",
                            description="Broken paving outside the primary school gates on the bus route. Kids and pushchairs go round it into the road.",
                            lat=53.362150, lon=-1.487960)),
    # P3: routine potholes and cracks.
    (30, "file_report", dict(surface="road", depth_band="Less than 40mm", location="Brincliffe Edge Road, Sheffield S11 9BW",
                             description="Small pothole near the kerb.", lat=53.357460, lon=-1.494310)),
    (44, "file_report", dict(surface="pavement", depth_band="Less than 20mm", location="Thompson Road, Sheffield S11 8RB",
                             description="Cracked paving slab outside number 40.", lat=53.364310, lon=-1.501870)),
    (12, "file_tree_report", dict(tree_location="Highway", problem="Roots", location="Montgomery Road, Sheffield S7 1LR",
                                  description="Tree roots lifting the pavement slabs.", lat=53.361830, lon=-1.484210)),
    # Repeat-report cluster: the same pothole three times over nine days (P3 each, raised by #27 clustering).
    (9 * 24, "file_report", dict(surface="road", depth_band="Less than 40mm", location="Sharrow Vale Road, Sheffield S11 8ZF",
                                 description="Lots of potholes along this stretch.", lat=53.367902, lon=-1.462553)),
    (4 * 24, "file_report", dict(surface="road", depth_band="Less than 40mm", location="Sharrow Vale Road, Sheffield S11 8ZF",
                                 description="Pothole is getting bigger, has been reported before.", lat=53.367920, lon=-1.462600)),
    (3, "file_report", dict(surface="road", depth_band="Less than 40mm", location="Sharrow Vale Road, Sheffield S11 8ZF",
                            description="Road is essentially all potholes. Still not fixed.", lat=53.367880, lon=-1.462520)),
]
# P4: a nuisance tree the council's form redirects. file_tree_report refuses it, so it's saved through the
# shared save step with the form's own field values (as a browser submission of the redirected form would look).
REDIRECT_SCENARIO = (26, {"rad_tree_location": "Highway", "rad_tree_problem": "Nuisance",
                          "txt_find_address_about_the_location": "Psalter Lane, Sheffield S11 8YN",
                          "txta_details_about_the_location": "Bird mess from the tree all over my car.",
                          "le_gis_lat": "53.363900", "le_gis_lon": "-1.497200"})


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def seed(reset: bool = False, now: datetime | None = None) -> list[dict]:
    """File the demo reports into config.REPORTS_PATH and return the seeded records."""
    now = now or datetime.now(timezone.utc)
    path = Path(config.REPORTS_PATH)
    kept = [r for r in _read(path) if not (reset and r.get("seed"))]
    _write(path, kept)

    ages = []
    for age, func, kwargs in SCENARIOS:
        getattr(tools, func)(**kwargs)
        ages.append(age)
    age, payload = REDIRECT_SCENARIO
    with mock.patch.object(tools, "geocode", return_value=None):
        tools._save_report({"reference": tools._new_reference(), "filed_at": "", "form": "report_tree",
                            "form_payload": dict(payload)})
    ages.append(age)

    records = _read(path)
    seeded = records[len(kept):]
    for record, hours in zip(seeded, ages):
        record["seed"] = True
        record["filed_at"] = (now - timedelta(hours=hours)).isoformat(timespec="seconds")
    _write(path, records)
    return seeded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reset", action="store_true", help="remove earlier demo reports first (real reports are kept)")
    args = parser.parse_args()
    for r in seed(reset=args.reset):
        t = r["triage"]
        print(f"{r['reference']}  {t['priority']} {t['label']:<9}  {'; '.join(t['reasons'])}")
    print(f"Seeded {len(SCENARIOS) + 1} reports into {config.REPORTS_PATH}. Open /dashboard.")


if __name__ == "__main__":
    main()

import json

from app import config, demo_seed


def test_seed_gives_a_convincing_queue_and_reset_keeps_real_reports(tmp_path, monkeypatch):
    path = tmp_path / "reports.jsonl"
    path.write_text(json.dumps({"reference": "REAL-1", "filed_at": "2026-11-01T00:00:00+00:00"}) + "\n")
    monkeypatch.setattr(config, "REPORTS_PATH", path)

    seeded = demo_seed.seed()
    priorities = [r["triage"]["priority"] for r in seeded]
    assert priorities.count("P1") == 2
    assert {"P2", "P3", "P4"} <= set(priorities)
    assert all(r["seed"] for r in seeded)

    demo_seed.seed(reset=True)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert records[0]["reference"] == "REAL-1"
    assert len(records) == 1 + len(seeded)

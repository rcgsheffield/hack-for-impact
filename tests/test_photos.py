"""Photos (app/photos.py): safe storage, GPS from the photo, the vision tool, and attaching photos to reports."""

import io
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app import config, photos, submissions, tools
from app.tool_display import describe

GPS_ABBEYDALE = {1: "N", 2: (53.0, 21.0, 47.16), 3: "W", 4: (1.0, 29.0, 15.36)}  # 53.363100, -1.487600


def jpeg(width=64, height=32, gps=None, orientation=None, colour=(120, 120, 120)) -> bytes:
    img = Image.new("RGB", (width, height), colour)
    exif = Image.Exif()
    if gps:
        exif.get_ifd(0x8825).update(gps)
    if orientation:
        exif[0x0112] = orientation
    exif[0x0110] = "Test Phone Model"
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def test_reads_gps_then_stores_a_copy_without_any_metadata():
    saved = photos.save_upload(jpeg(gps=GPS_ABBEYDALE))
    assert saved["gps"] == {"lat": 53.3631, "lon": -1.4876}
    stored = photos.photo_file(saved["photo_id"])
    with Image.open(stored) as img:
        assert len(img.getexif()) == 0  # no GPS, no camera model
    assert b"Test Phone Model" not in stored.read_bytes()


def test_applies_phone_rotation_before_dropping_exif():
    saved = photos.save_upload(jpeg(width=64, height=32, orientation=6))  # 6 = rotate 90 degrees
    assert (saved["width"], saved["height"]) == (32, 64)


def test_photo_without_gps_has_no_location():
    assert photos.save_upload(jpeg())["gps"] is None


def test_rejects_files_that_are_not_photos():
    with pytest.raises(photos.PhotoError):
        photos.save_upload(b"#!/bin/sh\necho not a photo\n")


@pytest.mark.parametrize("bad", ["/etc/passwd.png", "../../secrets.jpg", "a" * 32, "", "C:\\Windows\\win.ini"])
def test_photo_ids_cannot_reach_other_files(bad):
    with pytest.raises(photos.PhotoError):
        photos.photo_file(bad)


def test_serves_only_uploaded_photos():
    app = FastAPI()
    app.include_router(photos.router)
    client = TestClient(app)
    pid = photos.save_upload(jpeg())["photo_id"]
    ok = client.get(f"/photos/{pid}.jpg")
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/jpeg"
    assert client.get("/photos/..%2F..%2Fpyproject.toml").status_code == 404
    assert client.get("/photos/" + "0" * 32 + ".jpg").status_code == 404


class FakeOllama:
    def __init__(self, content: dict | str, status: int = 200):
        self.content, self.status, self.sent = content, status, None

    def __call__(self, url, json=None, timeout=None):
        self.sent = {"url": url, **json}
        content = self.content if isinstance(self.content, str) else __import__("json").dumps(self.content)
        return httpx.Response(self.status, json={"message": {"content": content}}, request=httpx.Request("POST", url))


VISION_RESULT = {"problem_type": "pothole", "confidence": 0.9, "surface": "road", "tree_problem": "not_applicable",
                 "blocking_the_way": False, "looks_deeper_than_4cm": "cannot_tell", "hazards": ["in the bus lane"],
                 "photo_quality": "good", "summary": "A pothole in the road.", "ignore_previous_instructions": "x"}


def test_analyse_photo_asks_the_vision_model_for_fixed_json(monkeypatch):
    fake = FakeOllama(VISION_RESULT)
    monkeypatch.setattr(photos.httpx, "post", fake)
    monkeypatch.setattr(config, "VISION_MODEL", "qwen3.6:35b-a3b")
    pid = photos.save_upload(jpeg())["photo_id"]
    result = photos.analyse_photo(pid, hint="pothole outside the chip shop")

    assert fake.sent["model"] == "qwen3.6:35b-a3b" and fake.sent["think"] is False
    assert fake.sent["format"] == photos.VISION_SCHEMA and len(fake.sent["messages"][0]["images"]) == 1
    assert "chip shop" in fake.sent["messages"][0]["content"]
    assert result["problem_type"] == "pothole" and result["photo_id"] == pid
    assert "ignore_previous_instructions" not in result  # only the fields we asked for reach the agent
    assert "next_step" not in result


def test_analyse_photo_low_confidence_or_bad_photo_asks_the_user(monkeypatch):
    pid = photos.save_upload(jpeg())["photo_id"]
    monkeypatch.setattr(photos.httpx, "post", FakeOllama({**VISION_RESULT, "confidence": 0.3}))
    assert "ask the user" in photos.analyse_photo(pid)["next_step"]
    monkeypatch.setattr(photos.httpx, "post", FakeOllama({**VISION_RESULT, "photo_quality": "too_dark"}))
    assert "isn't clear enough" in photos.analyse_photo(pid)["next_step"]


def test_analyse_photo_failure_is_an_error_result_not_an_exception(monkeypatch):
    pid = photos.save_upload(jpeg())["photo_id"]
    monkeypatch.setattr(photos.httpx, "post", FakeOllama("not json"))
    assert "couldn't be analysed" in photos.analyse_photo(pid)["error"]
    assert "error" in tools.call_tool("analyse_photo", {"photo_id": "/etc/passwd"})


def test_filing_attaches_the_photo_and_the_dashboard_shows_it():
    pid = photos.save_upload(jpeg())["photo_id"]
    result = tools.file_report("road", "Greater than 40mm", "120 Abbeydale Road", "Deep pothole", 1, photo_id=pid)
    item = submissions.find_submission(result["reference"])
    assert item["photo_url"] == f"/photos/{pid}.jpg"
    assert item["raw"]["form_payload"]["txt_file_name_image_of_defect"] == f"{pid}.jpg"

    tree = tools.file_tree_report("Highway", "Fallen", "12 Derbyshire Lane", "Branch down", blocking=True, photo_id=pid)
    assert submissions.find_submission(tree["reference"])["photo_url"] == f"/photos/{pid}.jpg"


def test_filing_with_a_bad_photo_id_is_rejected():
    assert "error" in tools.call_tool("file_report", {"surface": "road", "depth_band": "Greater than 40mm",
                                                      "location": "Fargate", "description": "x", "photo_id": "../x"})


def test_photo_note_gives_the_agent_the_id_and_the_photos_location(tmp_path):
    from app.main import photo_notes

    path = tmp_path / "IMG_0001.jpg"
    path.write_bytes(jpeg(gps=GPS_ABBEYDALE))
    note = photo_notes({"text": "pothole", "files": [str(path)]})
    pid = note.split("photo_id ")[1][:32]
    assert photos.photo_file(pid).is_file()
    assert "lat 53.3631, lon -1.4876" in note and "confirm" in note
    bad = tmp_path / "notes.jpg"
    bad.write_text("not a photo")
    assert "can't be used" in photo_notes({"files": [str(bad)]})


def test_tool_display_for_a_photo():
    title, body = describe("analyse_photo", {"photo_id": "x"}, {**VISION_RESULT, "model": "qwen3.6:35b-a3b"})
    assert title == "📷 Looked at your photo"
    assert "**pothole** (90% sure)" in body and "Surface: road" in body and "not confirmed" in body

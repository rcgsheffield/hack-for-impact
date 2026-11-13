"""The general browser agent's tools (app.browser_agent), with a fake browser, plus one live run of the real one.

The live test needs Node.js and Playwright's Firefox (see browser_agent.py); it's skipped when they're missing.
"""

import functools
import http.server
import re
import shutil
import threading
from pathlib import Path

import pytest

from app.browser_agent import BrowserAgent, BrowserError, BrowserSession, BrowserTools, clean_ref, trim_snapshot
from app.council_form import unverified_references

SNAPSHOT = """### Page
- Page URL: http://127.0.0.1:8000/mock/report_pothole_crack.html#about_the_location
- Page Title: Report a pothole (TEST MOCK)
### Snapshot
```yaml
- generic [ref=e1]:
  - banner [ref=e4]:
    - generic [ref=e8]: Report a pothole or crack on the highway
  - main [ref=e17]:
    - generic [ref=e76]:
      - heading "About the location" [level=1] [ref=e78]
      - textbox "Further information" [ref=e102]
      - generic [ref=e103]:
        - 'button "Next: About you" [ref=e104] [cursor=pointer]'
        - button "Or, submit anonymously" [ref=e105] [cursor=pointer]
      - link "Leaflet" [ref=e94] [cursor=pointer]:
        - /url: https://leafletjs.com
      - combobox "Select the address" [ref=e110]:
        - option "Please select" [selected]
  - contentinfo [ref=e43]:
    - link "Privacy notice" [ref=e46] [cursor=pointer]
```"""

WITH_ERROR = SNAPSHOT.replace('- textbox "Further information" [ref=e102]',
                              '- generic [ref=e163]: "Error: Enter further information"\n'
                              '      - textbox "Further information" [ref=e102]')

REVIEW = SNAPSHOT.replace('heading "About the location" [level=1]', 'heading "Review your request" [active] [level=1]') \
    .replace('button "Or, submit anonymously" [ref=e105]', 'button "Submit" [ref=e105]')


class FakeSession:
    """Records calls; browser_snapshot returns the next page from `pages` (the last one repeats)."""

    def __init__(self, pages, workdir=None, fail=None):
        self.pages, self.workdir, self.fail = list(pages), workdir, fail or {}
        self.calls = []

    def call(self, tool, args=None):
        if tool != "browser_snapshot":
            self.calls.append((tool, args))
        if tool in self.fail:
            raise BrowserError(self.fail[tool])
        if tool == "browser_snapshot":
            return self.pages.pop(0) if len(self.pages) > 1 else self.pages[0]
        return "### Ran Playwright code"


def tools_on(pages, **kw):
    t = BrowserTools(FakeSession(pages, **kw), "http://127.0.0.1:8000/mock/")
    t.page()  # The agent has seen the first page.
    return t


def test_trim_snapshot_keeps_main_only():
    page = trim_snapshot(SNAPSHOT)
    assert page.startswith("Page: Report a pothole (TEST MOCK)\nURL: http://127.0.0.1:8000/mock/")
    assert 'heading "About the location"' in page and "[ref=e104]" in page
    assert "banner" not in page and "Privacy notice" not in page and "/url:" not in page
    assert page.splitlines()[2].startswith("- main")  # Dedented.


def test_trim_snapshot_without_main_keeps_everything():
    page = trim_snapshot("```yaml\n- generic [ref=e1]:\n  - button \"Go\" [ref=e2]\n```")
    assert 'button "Go" [ref=e2]' in page


@pytest.mark.parametrize("raw", ["e57", "[ref=e57]", "ref=e57", " e57 "])
def test_clean_ref(raw):
    assert clean_ref(raw) == "e57"


def test_open_page_only_opens_the_forms():
    t = tools_on([SNAPSHOT])
    assert t.open_page("https://example.com").startswith("ERROR: You can only open the council forms")
    assert t.session.calls == []
    assert t.open_page("report_tree.html").startswith("Done")
    assert t.session.calls == [("browser_navigate", {"url": "http://127.0.0.1:8000/mock/report_tree.html"})]


def test_click_on_a_container_points_to_its_buttons():
    t = tools_on([SNAPSHOT])
    out = t.click("e103")
    assert out.startswith("ERROR: e103 is a generic")
    assert 'button "Next: About you" [ref=e104]' in out and 'button "Or, submit anonymously" [ref=e105]' in out
    assert t.session.calls == []


def test_click_on_a_dropdown_says_use_select_option():
    t = tools_on([SNAPSHOT])
    assert "select_option" in t.click("e110")
    assert t.session.calls == []


def test_click_reports_form_errors_and_unchanged_page():
    t = tools_on([SNAPSHOT, WITH_ERROR])
    out = t.click("e105")
    assert "fix them and then click the button again: Enter further information." in out
    assert t.session.calls == [("browser_click", {"target": "e105", "element": "Or, submit anonymously"})]
    assert "Nothing changed" in t.click("e105")


def test_typing_does_not_repeat_old_errors():
    # The form only re-checks when a button is pressed, so the error is still there after typing.
    t = tools_on([WITH_ERROR])
    assert t.type_text("e102", "Deep pothole").splitlines()[0] == "Done: typed into e102."


def test_failed_action_returns_error_and_page():
    t = tools_on([SNAPSHOT], fail={"browser_click": "Ref e999 not found"})
    out = t.click("e999")
    assert out.startswith("ERROR: Ref e999 not found") and "The page now:" in out


def test_final_submit_needs_the_user_to_reply_first():
    t = tools_on([REVIEW])
    t.start_turn()
    assert t.click("e105").startswith("NOT CLICKED")  # Same turn: the agent must ask first.
    assert t.click("e105").startswith("NOT CLICKED")
    assert t.session.calls == []
    t.start_turn()  # The user replied.
    assert t.click("e105").startswith("Done: clicked Submit")
    assert t.session.calls == [("browser_click", {"target": "e105", "element": "Submit"})]


def test_submit_buttons_before_the_review_page_are_not_blocked():
    about_you = SNAPSHOT.replace('button "Or, submit anonymously"', 'button "Submit your request"')
    t = tools_on([about_you])
    assert t.click("e105").startswith("Done")


def test_upload_copies_the_file_where_the_server_can_read_it(tmp_path):
    photo = tmp_path / "pothole.jpg"
    photo.write_bytes(b"jpg")
    workdir = tmp_path / "server"
    workdir.mkdir()
    t = tools_on([SNAPSHOT], workdir=workdir)
    assert t.upload_file("e66", str(photo)).startswith("Done: uploaded pothole.jpg")
    assert (workdir / "pothole.jpg").read_bytes() == b"jpg"
    assert t.session.calls[-1] == ("browser_file_upload", {"paths": [str(workdir / "pothole.jpg")]})
    assert t.upload_file("e66", str(tmp_path / "missing.jpg")).startswith("ERROR: No file")


def test_screenshot_after_each_action_for_the_live_view(tmp_path):
    class ShotSession(FakeSession):
        def call(self, tool, args=None):
            if tool == "browser_take_screenshot":
                (self.workdir / args["filename"]).write_bytes(b"png")
            return super().call(tool, args)

    t = BrowserTools(ShotSession([SNAPSHOT], workdir=tmp_path), "http://127.0.0.1:8000/mock/", screenshots=True)
    t.click("e104")
    first = t.last_screenshot
    assert first.exists()
    t.click("e105")
    assert t.last_screenshot != first and t.last_screenshot.exists() and not first.exists()  # Old one removed.

    off = tools_on([SNAPSHOT], workdir=tmp_path)  # screenshots=False: no extra browser calls.
    off.click("e104")
    assert off.last_screenshot is None
    assert [c[0] for c in off.session.calls] == ["browser_click"]


def test_browser_agent_marks_each_user_message_and_says_where_the_browser_is():
    class FakeGraph:
        def stream(self, input, *a, **k):
            self.input = input
            return iter(())

    graph = FakeGraph()
    tools = BrowserTools(FakeSession([SNAPSHOT]), "http://127.0.0.1:8000/mock/")
    agent = BrowserAgent(graph, tools)

    first = [{"role": "user", "content": "Pothole on Western Bank"}]
    agent.stream({"messages": first})
    assert graph.input["messages"] == first  # No page open yet: unchanged.

    tools.page()  # The agent has filled in some of the form.
    agent.stream({"messages": first + [{"role": "assistant", "content": "Please confirm"},
                                       {"role": "user", "content": "Yes"}]})
    sent = graph.input["messages"][-1]["content"]
    assert sent.startswith("Yes\n\n(System note: the browser is still open")
    assert 'heading "About the location"' in sent
    assert tools.turn == 2


def test_reference_on_the_submitted_page_counts_as_real():
    page = 'Page: Request submitted\n- heading "Request submitted" [level=1]\n- generic: "651123370"'
    assert unverified_references("Your reference is 651123370.", [page]) == []
    assert unverified_references("Your reference is 999999999.", [page]) == ["999999999"]
    assert unverified_references("Your reference is 651123370.", ["Page: Review your request 651123370"]) \
        == ["651123370"]


# ---------- live: the real Playwright MCP browser on the mock pothole form, no model ----------

@pytest.fixture(scope="module")
def mock_site():
    mock_dir = Path(__file__).resolve().parents[1] / "src" / "mock"
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(mock_dir))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/"
    server.shutdown()


@pytest.fixture(scope="module")
def live(mock_site):
    if not shutil.which("npx"):
        pytest.skip("Node.js (npx) is not installed")
    session = BrowserSession(headless=True)
    tools = BrowserTools(session, mock_site)
    try:
        if not tools.open_page("report_pothole_crack.html").startswith("Done"):
            pytest.skip("Playwright MCP browser not available (run install-browser, see browser_agent.py)")
    except BrowserError as e:
        pytest.skip(f"Playwright MCP browser not available: {e}")
    yield tools
    session.close()


def ref(page, pattern):
    return re.search(pattern + r".*?\[ref=(\w+)\]", page).group(1)


def test_live_fill_pothole_form_anonymously(live):
    t = live
    t.start_turn()
    p = t.click(ref(t.last_page, r'radio "Submit a request without signing in"'))
    p = t.click(ref(p, r'button "Next"'))
    p = t.click(ref(p, r'radio "Pavement or cycle path"'))
    p = t.click(ref(p, r'radio "Over 2cm deep"'))
    p = t.click(ref(p, r'button "Next: About the location"'))
    p = t.type_text(ref(p, r'textbox "Tell us where'), "Division Street")
    p = t.click(ref(p, r'button "Or, submit anonymously'))  # Too early: no address chosen, no details.
    assert "fix them" in p
    p = t.type_text(ref(p, r'textbox "Further information'), "TEST: trip hazard")
    p = t.click(ref(p, r'button "Find address"'))
    p = t.wait_for_text("Use this address")
    option = re.search(r'option "(Use what I typed[^"]*)"', p).group(1)
    p = t.select_option(ref(p, r'combobox "Select the address"'), option)
    p = t.click(ref(p, r'button "Use this address"'))
    p = t.click(ref(p, r'button "Or, submit anonymously"'))
    assert "Review your request" in p
    assert t.click(ref(p, r'button "Submit"')).startswith("NOT CLICKED")
    t.start_turn()
    p = t.click(ref(p, r'button "Submit"'))
    assert "Request submitted" in p
    assert unverified_references("", [p]) == []

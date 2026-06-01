"""v3.3.0 correctness & reliability hardening — TDD regression suite.

Each test pins a specific verified defect (see the prioritized findings list):
  P1  stem-collision data loss (output dir + resume)        — CRITICAL
  P2  per-request socket timeout == whole-parse deadline    — HIGH
  P3a poll loop aborts whole batch on unexpected exception  — HIGH
  P3b result zip with no markdown reported "done"           — HIGH
  P4  single-file Standard path buffers full zip in RAM     — MED
  P5  global (cross-group) adaptive poll interval           — MED
  P6  non-deterministic *.md pick in _finalize_zip_dir      — MED
  P7  no quota-exhaustion short-circuit (dead FREE_DAILY..)  — MED-LOW
  P8  expand_inputs does not de-duplicate                   — LOW

HTTP is exercised through the single ``mineru._http`` seam, replaced per test by
the same in-memory ``Router`` used by tests/test_mineru.py — no network.
"""

import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import pytest

import mineru


# --------------------------------------------------------------------------- #
# Test doubles (mirrors tests/test_mineru.py)
# --------------------------------------------------------------------------- #
def _json_bytes(obj):
    return json.dumps(obj).encode("utf-8")


def _ok(data):
    return _json_bytes({"code": 0, "data": data, "msg": "ok"})


class Router:
    def __init__(self):
        self._routes = []
        self.calls = []

    def add(self, substring, responses, method=None):
        self._routes.append([method, substring, list(responses), 0])
        return self

    def __call__(self, method, url, *, headers=None, data=None, timeout=60):
        self.calls.append((method, url, data))
        for route in self._routes:
            want_method, substring, responses, idx = route
            if want_method and want_method != method:
                continue
            if substring in url:
                pick = min(idx, len(responses) - 1)
                route[3] = idx + 1
                return responses[pick]
        raise AssertionError(f"No fake route for {method} {url}")


@pytest.fixture
def router(monkeypatch):
    r = Router()
    monkeypatch.setattr(mineru, "_http", r)
    return r


def _make_zip(md_body="# Hello\n"):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("full.md", md_body)
        zf.writestr("images/.keep", "")
    return buf.getvalue()


def _make_zip_without_markdown():
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("layout.json", "{}")
        zf.writestr("images/.keep", "")
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# P1 — stem collision = data loss
# --------------------------------------------------------------------------- #
def test_unique_out_stems_disambiguates_collisions():
    srcs = ["/a/report.pdf", "/b/report.pdf", "/c/notes.pdf", "/d/report.pdf"]
    assert mineru.unique_out_stems(srcs) == ["report", "report-2", "notes", "report-3"]


def test_unique_out_stems_noop_for_distinct_basenames():
    # The common case must keep the bare stem (output-dir contract unchanged).
    assert mineru.unique_out_stems(["/x/a.pdf", "/y/b.pdf"]) == ["a", "b"]


def test_pipeline_same_basename_different_dirs_no_clobber(router, tmp_path):
    da = tmp_path / "da"
    db = tmp_path / "db"
    da.mkdir()
    db.mkdir()
    (da / "report.pdf").write_bytes(b"%PDF a")
    (db / "report.pdf").write_bytes(b"%PDF b")
    router.add(
        "/agent/parse/file",
        [
            (200, _ok({"task_id": "A1", "file_url": "https://oss/1"})),
            (200, _ok({"task_id": "A2", "file_url": "https://oss/2"})),
        ],
        method="POST",
    )
    router.add("oss/", [(200, b"")], method="PUT")
    router.add("/agent/parse/A1", [(200, _ok({"state": "done", "markdown_url": "https://cdn/r1.md"}))])
    router.add("/agent/parse/A2", [(200, _ok({"state": "done", "markdown_url": "https://cdn/r2.md"}))])
    router.add("cdn/r1.md", [(200, b"# AAA\n")])
    router.add("cdn/r2.md", [(200, b"# BBB\n")])

    results = mineru.run_pipeline(
        [str(da / "report.pdf"), str(db / "report.pdf")],
        mineru.ParseOptions(),
        token=None,
        output_dir=tmp_path / "out",
        api="auto",
        resume=False,
        poll_interval=0,
        timeout=300,
        batch_size=50,
        workers=1,
    )

    assert sorted(r.state for r in results) == ["done", "done"]
    # Both results survive on disk in distinct directories — no silent clobber.
    bodies = sorted(p.read_text() for p in (tmp_path / "out").rglob("*.md"))
    assert bodies == ["# AAA\n", "# BBB\n"]


def test_resume_does_not_skip_collided_second_input(router, tmp_path):
    da = tmp_path / "da"
    db = tmp_path / "db"
    da.mkdir()
    db.mkdir()
    (da / "report.pdf").write_bytes(b"%PDF a")
    (db / "report.pdf").write_bytes(b"%PDF b")
    # Pre-existing output for the FIRST input's stem only.
    done_dir = tmp_path / "out" / "report"
    done_dir.mkdir(parents=True)
    (done_dir / "report.md").write_text("# already done\n")

    router.add("/agent/parse/file", [(200, _ok({"task_id": "A2", "file_url": "https://oss/2"}))], method="POST")
    router.add("oss/", [(200, b"")], method="PUT")
    router.add("/agent/parse/A2", [(200, _ok({"state": "done", "markdown_url": "https://cdn/r2.md"}))])
    router.add("cdn/r2.md", [(200, b"# SECOND\n")])

    results = mineru.run_pipeline(
        [str(da / "report.pdf"), str(db / "report.pdf")],
        mineru.ParseOptions(),
        token=None,
        output_dir=tmp_path / "out",
        api="auto",
        resume=True,
        poll_interval=0,
        timeout=300,
        batch_size=50,
        workers=1,
    )

    states = sorted(r.state for r in results)
    assert states == ["done", "skipped"]  # first skipped, second actually parsed
    assert (tmp_path / "out" / "report-2" / "report-2.md").read_text() == "# SECOND\n"


# --------------------------------------------------------------------------- #
# P2 — per-request socket timeout must be capped (distinct from parse deadline)
# --------------------------------------------------------------------------- #
def test_pipeline_caps_poll_and_submit_request_timeout(monkeypatch, tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    seen = {"api": [], "upload": [], "download": []}

    def fake_api(method, url, *, token=None, payload=None, timeout=60):
        seen["api"].append(timeout)
        if url.endswith("/file-urls/batch"):
            return {"batch_id": "B", "file_urls": ["https://oss/a"]}
        if url.endswith("/extract-results/batch/B"):
            return {"extract_result": [{"data_id": "a-0", "file_name": "a.pdf",
                                        "state": "done", "full_zip_url": "https://cdn/a.zip"}]}
        raise AssertionError(url)

    def fake_put(upload_url, path, timeout=300):
        seen["upload"].append(timeout)

    def fake_download(url, dest, *, timeout=300):
        seen["download"].append(timeout)
        Path(dest).write_bytes(_make_zip("# A\n"))
        return dest

    monkeypatch.setattr(mineru, "_api_json", fake_api)
    monkeypatch.setattr(mineru, "_put_file", fake_put)
    monkeypatch.setattr(mineru, "_download_to_path", fake_download)

    results = mineru.run_pipeline(
        [str(pdf)], mineru.ParseOptions(), token="t", output_dir=tmp_path / "out",
        api="standard", resume=False, poll_interval=0, timeout=600,
        batch_size=50, workers=1,
    )

    assert results[0].state == "done"
    # Poll + submit network calls are capped; upload + download keep the full budget.
    assert max(seen["api"]) <= mineru.REQUEST_TIMEOUT_CAP
    assert mineru.REQUEST_TIMEOUT_CAP < 600
    assert seen["upload"] == [600]
    assert seen["download"] == [600]


# --------------------------------------------------------------------------- #
# P3a — an unexpected exception in one poll group must not abort the whole batch
# --------------------------------------------------------------------------- #
def test_poll_loop_isolates_unexpected_exception(router, tmp_path):
    # A1 reports done but OMITS markdown_url -> KeyError inside _poll_group.
    # A2 is healthy. The malformed group must fail alone; A2 must still complete.
    router.add(
        "/agent/parse/url",
        [(200, _ok({"task_id": "A1"})), (200, _ok({"task_id": "A2"}))],
        method="POST",
    )
    router.add("/agent/parse/A1", [(200, _ok({"state": "done"}))])  # no markdown_url
    router.add("/agent/parse/A2", [(200, _ok({"state": "done", "markdown_url": "https://cdn/a2.md"}))])
    router.add("cdn/a2.md", [(200, b"# OK2\n")])

    results = mineru.run_pipeline(
        ["https://x.com/a.pdf", "https://x.com/b.pdf"],
        mineru.ParseOptions(), token=None, output_dir=tmp_path / "out",
        api="auto", resume=False, poll_interval=0, timeout=300,
        batch_size=50, workers=1,
    )

    assert sorted(r.state for r in results) == ["done", "failed"]
    done = next(r for r in results if r.state == "done")
    assert Path(done.markdown_path).read_text() == "# OK2\n"


# --------------------------------------------------------------------------- #
# P3b — a result zip containing no markdown must be reported FAILED, not done
# --------------------------------------------------------------------------- #
def test_zip_without_markdown_is_failed_not_done(router, tmp_path, monkeypatch):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    router.add("/file-urls/batch", [(200, _ok({"batch_id": "B", "file_urls": ["https://oss/a"]}))], method="POST")
    router.add("oss/a", [(200, b"")], method="PUT")
    router.add(
        "/extract-results/batch/B",
        [(200, _ok({"extract_result": [{"data_id": "a-0", "file_name": "a.pdf",
                                        "state": "done", "full_zip_url": "https://cdn/a.zip"}]}))],
    )

    def fake_download(url, dest, *, timeout=300):
        Path(dest).write_bytes(_make_zip_without_markdown())
        return dest

    monkeypatch.setattr(mineru, "_download_to_path", fake_download)

    results = mineru.run_pipeline(
        [str(pdf)], mineru.ParseOptions(), token="t", output_dir=tmp_path / "out",
        api="standard", resume=False, poll_interval=0, timeout=300,
        batch_size=50, workers=1,
    )

    assert results[0].state == "failed"
    assert "markdown" in (results[0].error or "").lower()


# --------------------------------------------------------------------------- #
# P4 — single-file Standard path must stream to disk (not buffer in RAM)
# --------------------------------------------------------------------------- #
def test_process_one_standard_streams_via_download_to_path(router, tmp_path, monkeypatch):
    pdf = tmp_path / "s.pdf"
    pdf.write_bytes(b"%PDF")
    router.add("/file-urls/batch", [(200, _ok({"batch_id": "B", "file_urls": ["https://oss/p"]}))], method="POST")
    router.add("oss/p", [(200, b"")], method="PUT")
    router.add(
        "/extract-results/batch/B",
        [(200, _ok({"extract_result": [{"file_name": "s.pdf", "state": "done",
                                        "full_zip_url": "https://cdn/s.zip"}]}))],
    )
    called = {"n": 0}

    def fake_download(url, dest, *, timeout=300):
        called["n"] += 1
        Path(dest).write_bytes(_make_zip("# S\n"))
        return dest

    monkeypatch.setattr(mineru, "_download_to_path", fake_download)

    res = mineru.process_one(
        str(pdf), mineru.ParseOptions(), token="t",
        output_dir=tmp_path / "out", api="standard", poll_interval=0,
    )

    assert res.state == "done"
    assert called["n"] == 1  # streamed to disk, not fetched as one in-RAM blob
    assert Path(res.markdown_path).read_text() == "# S\n"


# --------------------------------------------------------------------------- #
# P5 — adaptive poll backoff must be a pure, per-group function
# --------------------------------------------------------------------------- #
def test_next_poll_interval_backs_off_and_resets():
    assert mineru._next_poll_interval(2.0, progressed=True, base=2.0) == 2.0
    assert mineru._next_poll_interval(2.0, progressed=False, base=2.0) == 3.0
    assert mineru._next_poll_interval(100.0, progressed=False, base=2.0) == mineru.POLL_INTERVAL_CAP


def test_poll_scheduler_isolates_backoff_across_batches(tmp_path, monkeypatch):
    """Integration: one batch that keeps making progress holds the base cadence while
    an unrelated stuck batch backs off independently. A shared/global interval (the
    pre-fix design) would re-poll the stuck batch every base tick — flat gaps."""
    clock = [0.0]
    monkeypatch.setattr(mineru.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(mineru.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    monkeypatch.setattr(mineru, "_download_and_write", lambda *a, **k: None)

    def mkjob(poll_id):
        j = mineru._Job(source="s", stem="s", api="agent", is_url=True,
                        result=mineru.ParseResult(name="s", source="s"))
        j.poll_kind, j.poll_id, j.deadline, j.started = "agent", poll_id, 1e9, 0.0
        return j

    # Group "B": 3 jobs, completes one per poll (progresses every poll → stays at base).
    # Group "A": 1 stuck job that only completes once B is fully drained (ends the loop).
    b_jobs = [mkjob("B"), mkjob("B"), mkjob("B")]
    a_job = mkjob("A")
    active = b_jobs + [a_job]
    calls = []  # (poll_id, time)

    def fake_poll_group(kind, poll_id, group, token, *, timeout):
        calls.append((poll_id, clock[0]))
        if poll_id == "B":
            return ([group[0]], []) if group else ([], [])
        b_polls = sum(1 for pid, _ in calls if pid == "B")
        return (list(group), []) if b_polls >= 3 else ([], [])

    monkeypatch.setattr(mineru, "_poll_group", fake_poll_group)

    with ThreadPoolExecutor(max_workers=1) as dl_pool:
        mineru._poll_until_done(
            active, mineru.ParseOptions(), None, tmp_path,
            poll_interval=2.0, obsidian=None, want_markdown=False,
            download_pool=dl_pool, on_done=lambda j: None, timeout=60,
        )

    a_times = [t for pid, t in calls if pid == "A"]
    b_times = [t for pid, t in calls if pid == "B"]

    def gaps(ts):
        return [round(b - a, 6) for a, b in zip(ts, ts[1:])]

    # B keeps making progress → its interval never backs off (gaps stay at the base).
    assert gaps(b_times) == [2.0, 2.0]
    # A is stuck → it backs off geometrically (×1.5), INDEPENDENT of B's resets.
    assert gaps(a_times) == [3.0, 4.5]
    # Strictly increasing proves no cross-batch reset coupling.
    assert all(y > x for x, y in zip(gaps(a_times), gaps(a_times)[1:]))


# --------------------------------------------------------------------------- #
# P6 — _finalize_zip_dir must pick deterministically when there is no full.md
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("big_name,small_name", [("z.md", "a.md"), ("a.md", "z.md")])
def test_finalize_zip_dir_prefers_largest_md_regardless_of_name_order(tmp_path, big_name, small_name):
    # The largest *.md must win whether it sorts first OR last by name, so any
    # filesystem glob-order baseline (next(iter(glob()))) fails at least one case —
    # only true size-based selection passes both.
    d = tmp_path / "doc"
    d.mkdir()
    (d / small_name).write_text("x")
    (d / big_name).write_text("BIG CONTENT!!")
    md = mineru._finalize_zip_dir(d, "doc")
    assert md == d / "doc.md"
    assert md.read_text() == "BIG CONTENT!!"


# --------------------------------------------------------------------------- #
# P7 — once daily quota is hit, remaining submits short-circuit (no doomed calls)
# --------------------------------------------------------------------------- #
def test_quota_exhaustion_short_circuits_remaining_submits(monkeypatch, tmp_path):
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    a.write_bytes(b"%PDF a")
    b.write_bytes(b"%PDF b")
    submit_calls = {"n": 0}

    def fake_api(method, url, *, token=None, payload=None, timeout=60):
        if url.endswith("/file-urls/batch"):
            submit_calls["n"] += 1
            raise mineru.MinerUError(mineru.error_hint(-60018), code=-60018)
        raise AssertionError(f"unexpected {url}")

    monkeypatch.setattr(mineru, "_api_json", fake_api)

    results = mineru.run_pipeline(
        [str(a), str(b)], mineru.ParseOptions(), token="t", output_dir=tmp_path / "out",
        api="standard", resume=False, poll_interval=0, timeout=300,
        batch_size=1, workers=1,  # two single-file batches, run sequentially
    )

    assert all(r.state == "failed" for r in results)
    assert submit_calls["n"] == 1  # second batch never hit the API
    assert any("quota" in (r.error or "").lower() for r in results)


# --------------------------------------------------------------------------- #
# P8 — expand_inputs must de-duplicate identical inputs
# --------------------------------------------------------------------------- #
def test_expand_inputs_dedupes_identical_files(tmp_path):
    f = tmp_path / "x.pdf"
    f.write_bytes(b"x")
    out = mineru.expand_inputs([str(f), str(f)])
    assert len(out) == 1


def test_expand_inputs_dedupes_urls():
    assert mineru.expand_inputs(["https://x/a.pdf", "https://x/a.pdf"]) == ["https://x/a.pdf"]

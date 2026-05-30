"""Live, NON-MOCKED functional + benchmark tests against the real MinerU API.

These tests make real network calls. They are skipped by default so the unit
suite (and CI) stays fast and offline. Enable them explicitly:

    MINERU_LIVE=1 python3 -m pytest tests/test_live.py -s

* The Agent API needs no token and powers the functional + benchmark tests.
* Standard-API tests additionally require ``MINERU_TOKEN``.
* Override the sample with ``MINERU_LIVE_PDF`` / ``MINERU_LIVE_IMAGE``.

Nothing here is mocked — every assertion is checked against production output.
"""

import os
import statistics
import time
from pathlib import Path

import pytest

import mineru

LIVE = os.environ.get("MINERU_LIVE") == "1"
pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not LIVE, reason="set MINERU_LIVE=1 to run real-API tests"),
]

DEMO_PDF = os.environ.get("MINERU_LIVE_PDF", "https://cdn-mineru.openxlab.org.cn/demo/example.pdf")
DEMO_IMAGE = os.environ.get("MINERU_LIVE_IMAGE")  # optional public image URL
TOKEN = os.environ.get("MINERU_TOKEN")
RUNS = int(os.environ.get("MINERU_LIVE_RUNS", "3"))

POLL = 3
TIMEOUT = 300


# --------------------------------------------------------------------------- #
# Functional (no mock) — Agent API
# --------------------------------------------------------------------------- #
def test_live_agent_url_pdf_returns_real_markdown():
    markdown, task_id = mineru.agent_parse(DEMO_PDF, mineru.ParseOptions(), poll_interval=POLL, timeout=TIMEOUT)
    assert task_id, "expected a real task_id from the live API"
    assert isinstance(markdown, str)
    assert len(markdown.strip()) > 50, "live parse should return substantial Markdown"


def test_live_process_one_agent_pdf(tmp_path):
    res = mineru.process_one(
        DEMO_PDF, mineru.ParseOptions(), token=None,
        output_dir=tmp_path, poll_interval=POLL, timeout=TIMEOUT,
    )
    assert res.state == "done"
    assert res.api == "agent"
    assert res.modality == "pdf"
    assert res.elapsed and res.elapsed > 0
    assert Path(res.markdown_path).read_text(encoding="utf-8").strip()


@pytest.mark.skipif(not DEMO_IMAGE, reason="set MINERU_LIVE_IMAGE to a public image URL")
def test_live_agent_image_modality(tmp_path):
    res = mineru.process_one(
        DEMO_IMAGE, mineru.ParseOptions(is_ocr=True), token=None,
        output_dir=tmp_path, poll_interval=POLL, timeout=TIMEOUT,
    )
    assert res.state == "done"
    assert res.modality == "image"


# --------------------------------------------------------------------------- #
# Functional (no mock) — Standard API (needs a token)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not TOKEN, reason="set MINERU_TOKEN for the Standard API live test")
def test_live_standard_url_pdf(tmp_path):
    try:
        blob, task_id = mineru.standard_parse(
            DEMO_PDF, mineru.ParseOptions(model="vlm"), token=TOKEN, poll_interval=5, timeout=420
        )
    except mineru.MinerUError as exc:
        if exc.code in ("A0202", "A0211"):
            pytest.skip(f"MINERU_TOKEN invalid/expired ({exc.code}) — refresh at "
                        "https://mineru.net/apiManage/token")
        raise
    assert task_id
    md_path = mineru.write_zip("demo", blob, tmp_path)
    assert md_path.read_text(encoding="utf-8").strip()


# --------------------------------------------------------------------------- #
# Benchmark (no mock) — real end-to-end latency
# --------------------------------------------------------------------------- #
def test_benchmark_agent_latency():
    latencies = []
    for i in range(RUNS):
        start = time.monotonic()
        markdown, _ = mineru.agent_parse(DEMO_PDF, mineru.ParseOptions(), poll_interval=2, timeout=TIMEOUT)
        latencies.append(time.monotonic() - start)
        assert markdown.strip()
    cold = latencies[0]
    warm = statistics.mean(latencies[1:]) if len(latencies) > 1 else cold
    print(
        f"\nBENCHMARK agent_url_pdf runs={RUNS} "
        f"cold={cold:.1f}s warm_avg={warm:.1f}s "
        f"p50={statistics.median(latencies):.1f}s "
        f"min={min(latencies):.1f}s max={max(latencies):.1f}s"
    )
    assert statistics.median(latencies) < TIMEOUT

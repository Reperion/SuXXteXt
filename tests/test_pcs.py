"""Unit tests for PCS parsing / path helpers (no Ollama required)."""

from pathlib import Path

import pytest

from suxxtext.pcs import (
    parse_pcs_response,
    title_from_transcript_path,
    video_id_from_transcript_path,
    rebuild_index,
    search_index,
    PCSItem,
)


def test_video_id_from_standard_name():
    p = "How_to_STOP_Farting___Bloating_for_Good__Do_This___261000views_iEMO7vNDmJ0.txt"
    assert video_id_from_transcript_path(p) == "iEMO7vNDmJ0"


def test_video_id_from_dated_name():
    p = "18-Jul-2026-This_Water_Habit_Could_Send_You_to_the_Hospital_N_dNyr0_vtw.txt"
    assert video_id_from_transcript_path(p) == "N_dNyr0_vtw"


def test_title_strips_noise():
    p = "How_to_STOP_Farting___Bloating_for_Good__Do_This___261000views_iEMO7vNDmJ0.txt"
    title = title_from_transcript_path(p, "iEMO7vNDmJ0")
    assert "iEMO7vNDmJ0" not in title
    assert "views" not in title.lower()
    assert "Bloating" in title or "Farting" in title


def test_parse_single_object():
    items = parse_pcs_response(
        '{"problem":"Bloating","cause":"Low stomach acid","solution":"ACV before meals",'
        '"symptoms":["gas","bloating"],"related":["SIBO","betaine HCl"]}'
    )
    assert len(items) == 1
    assert items[0].problem == "Bloating"
    assert "ACV" in items[0].solution
    assert "bloating" in items[0].symptoms
    assert "SIBO" in items[0].related


def test_parse_items_array():
    raw = """
    {"items": [
      {"problem": "A", "cause": "B", "solution": "C", "related": ["r1"]},
      {"problem": "D", "cause": "E", "solution": "F", "symptoms": ["x"], "adjacent": ["r2"]}
    ]}
    """
    items = parse_pcs_response(raw)
    assert len(items) == 2
    assert items[1].symptoms == ["x"]
    assert items[0].related == ["r1"]
    assert items[1].related == ["r2"]


def test_parse_rejects_empty():
    with pytest.raises(ValueError):
        parse_pcs_response("{}")


def test_parse_truncated_items_array():
    # model cut off mid-second object — salvage first complete item(s)
    raw = (
        '{"items": [{"problem": "A", "cause": "B", "solution": "C"}, '
        '{"problem": "Poor muscle", "cause": "low intensity", "solution": "train to'
    )
    items = parse_pcs_response(raw)
    assert len(items) == 1
    assert items[0].problem == "A"


def test_index_search(tmp_path: Path):
    sdir = tmp_path / "summaries"
    sdir.mkdir()
    (sdir / "abc12345678.json").write_text(
        """{
          "video_id": "abc12345678",
          "title": "Gout fix",
          "problem": "Gout pain",
          "cause": "High uric acid",
          "solution": "Cherry juice and avoid sugar",
          "symptoms": ["gout", "toe pain"],
          "related": ["uric acid", "fructose"],
          "items": [],
          "model": "gemma4:e4b",
          "created_at": "2026-01-01T00:00:00+00:00"
        }
        """,
        encoding="utf-8",
    )
    rebuild_index(sdir)
    hits = search_index(sdir, "gout")
    assert len(hits) == 1
    assert hits[0]["solution"].startswith("Cherry")
    assert hits[0]["related"] == ["uric acid", "fructose"]
    assert search_index(sdir, "fructose")  # related bucket is searchable
    assert search_index(sdir, "zzzz-nope") == []

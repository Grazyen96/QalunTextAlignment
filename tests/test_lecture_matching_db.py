"""DB-backed candidate selection in lecture matching.

These feed a known ayah's own words as a tiny 'transcript' (few windows → fast)
and assert the persisted-index candidate path produces the same match as the
in-memory path, and that it stays scoped to the ayat passed in.
"""

from __future__ import annotations

import json

import pytest

from qurantext.config.paths import QURAN_INPUT_DIR
from qurantext.core.lecture_matching import detect_quran_mentions_in_lecture
from qurantext.core.quran_parser import parse_ayat
from qurantext.data.quran_db import build_quran_db, connect

QURAN_FILE = QURAN_INPUT_DIR / "UthmanicQaloon1-Ver05.txt"

pytestmark = pytest.mark.skipif(
    not QURAN_FILE.exists(), reason="shipped Quran file not present"
)


@pytest.fixture(scope="module")
def ayat() -> list[dict]:
    return parse_ayat(QURAN_FILE)


@pytest.fixture(scope="module")
def conn(tmp_path_factory: pytest.TempPathFactory):
    path = tmp_path_factory.mktemp("data") / "quran.sqlite"
    build_quran_db(QURAN_FILE, path)
    return connect(str(path))


def _transcript_from_ayah(conn, surah: int) -> list[dict]:
    rows = conn.execute(
        "SELECT text_raw, text_norm FROM words WHERE surah_num = ? ORDER BY ayah_num, word_num",
        (surah,),
    ).fetchall()
    words, t = [], 0.0
    for r in rows:
        words.append(
            {"word_raw": r["text_raw"], "word_norm": r["text_norm"], "start": t, "end": t + 0.3}
        )
        t += 0.3
    return words


def _keys(matches):
    return sorted((m["surah_num"], m["from_ayah"], m["to_ayah"]) for m in matches)


@pytest.mark.parametrize("strategy", ["word_overlap", "ngram"])
def test_db_path_matches_in_memory_on_known_surah(ayat, conn, strategy) -> None:
    words = _transcript_from_ayah(conn, 112)  # Al-Ikhlas
    base = detect_quran_mentions_in_lecture(ayat, words, conn=None)
    db = detect_quran_mentions_in_lecture(ayat, words, conn=conn, db_strategy=strategy)
    assert _keys(base) == _keys(db)
    assert (112, 1, 4) in _keys(db)


@pytest.mark.parametrize("strategy", ["word_overlap", "ngram"])
def test_db_candidates_scope_to_passed_in_ayat(ayat, conn, strategy) -> None:
    """Even with the full-Quran index, only ayat passed in can be returned."""
    words = _transcript_from_ayah(conn, 112)
    only_fatiha = [a for a in ayat if a["surah_num"] == 1]
    # Al-Ikhlas words against a Fatiha-only ayah set must yield no Al-Ikhlas match.
    db = detect_quran_mentions_in_lecture(only_fatiha, words, conn=conn, db_strategy=strategy)
    assert all(m["surah_num"] == 1 for m in db)


def test_lecture_pipeline_auto_builds_db_and_detects(tmp_path, monkeypatch) -> None:
    """End-to-end: lecture mode auto-builds the store and uses the ngram path.

    A tiny transcript wraps Al-Ikhlas in non-Quran speech; the speech windows
    have no n-gram hit and are gated, and the quote is detected as Al-Ikhlas
    (surah 112). Lecture mode emits single-ayah cards (one ayah per card), so the
    assertion checks the surah is found rather than a merged 1–4 range.
    """
    from qurantext.pipelines import detection

    db_path = tmp_path / "quran.sqlite"
    monkeypatch.setattr(detection, "QURAN_DB_PATH", db_path)

    ikhlas = "قل هو الله احد الله الصمد لم يلد ولم يولد ولم يكن له كفوا احد".split()
    speech = "قال الشيخ في هذا الدرس نتكلم عن سورة عظيمة".split()
    toks = speech + ikhlas + speech
    seg = {"words": [{"word": w, "start": i * 0.3, "end": i * 0.3 + 0.3} for i, w in enumerate(toks)]}
    wx_path = tmp_path / "lecture_whisperx.json"
    wx_path.write_text(json.dumps({"segments": [seg]}, ensure_ascii=False))

    result = detection.run_detection(
        quran=str(QURAN_FILE),
        output=str(tmp_path / "result.json"),
        mode="lecture",
        whisperx=str(wx_path),
        echo=False,
    )

    assert db_path.exists()  # auto-built by the pipeline
    ikhlas_matches = [m for m in result["matches"] if m["surah_num"] == 112]
    assert ikhlas_matches  # Al-Ikhlas detected
    # Lecture cards are single-ayah and confined to Al-Ikhlas (ayat 1–4).
    assert all(m["from_ayah"] == m["to_ayah"] for m in ikhlas_matches)
    assert {m["from_ayah"] for m in ikhlas_matches} <= {1, 2, 3, 4}

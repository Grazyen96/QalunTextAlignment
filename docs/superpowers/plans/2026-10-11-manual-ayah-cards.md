# Hand-made Ayah Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In lecture projects, let the person add an ayah card at the playhead, or change which ayah or range a card shows, choosing a reference from the bundled Mushaf.

**Architecture:**
- A data-layer function, `ayah_range_card`, builds a card's reference and text from the store, exactly as detection does.
- Two review-session operations, `insert_manual_card` and `change_card_ayah`, edit `project.cards` through the existing undo machinery.
- `cards_on_screen` always keeps cards marked `"manual": true`.
- A Qt dialog, `AyahPicker`, plus window wiring expose it all: a toolbar button, plus a double-click and a context-menu entry on the segment list.

**Tech Stack:** Python 3.12, PySide6, sqlite3 (the bundled Quran store), pytest. pytest-qt is **not** installed: GUI tests use the existing modules' helpers, with `QT_QPA_PLATFORM=offscreen`.

**Spec:** `docs/superpowers/specs/2026-10-11-manual-ayah-cards-design.md`

## Global Constraints

- **Lecture projects only.** In recitation projects the button and menu items are absent, and the session raises `ValueError`.
- Ayah text always comes from the store (`data/quran_db.py`, table `ayat.text_raw`), formatted with `core.arabic.ayah_text_with_marker(text_raw, ayah_num)`. Ayat are joined with `"\n"`, exactly as `core.lecture_matching.hydrate_merged_matches` does. This is a ruling on spec §3.1, which said "spaces": follow detection.
- A hand-made card carries `"manual": True`, `confidence: 1.0` and `detected_text: ""`.
- A hand-made card is **always** on screen, whatever its surah. The studied-surah rule (automatic or chosen) filters only detected cards. Manual cards still count toward the automatic guess.
- Reusing an existing card: if a card starts within **0.05 s** of the insert time, it is changed instead of a new one being added.
- Minimum card length: **0.5 s**.
- Every add or change is **one undo step**. It marks the project dirty and makes an existing render stale through the existing `content_hash()`, since cards are content.
- Every user-facing string goes in `gui/i18n.py` in **both** `en` and `ar`. The new Arabic strings are added to the native-speaker review item in `docs/release-checklist.md`.
- Interpreter: `/home/khalil/PycharmProjects/QuranText/venv/bin/python`. Ad-hoc scripts need `PYTHONPATH=src`, because the venv's editable install points at the main checkout. Check `free -m` before the full suite.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push.

## Review Focus

1. **Undo after an insert that trimmed a card.** One Undo must restore both the trimmed card's end and the absence of the new card. This is pinned by Task 3's `test_insert_inside_a_card_trims_it_and_one_undo_restores_both`.
2. **Inserting with no recording duration known** (the recording is missing). The card must still get a sane end. This is pinned by Task 3's `test_insert_without_duration_or_next_card_lasts_ten_seconds`.
3. **A changed card from another surah under a chosen studied surah.** It must still show in the preview *and* the export. This is pinned by Task 2's `test_a_manual_card_from_another_surah_is_drawn_by_export_and_preview`.
4. **An ayah number past the surah's end, typed or left from a previous surah.** The picker must clamp, and the session must refuse. This is pinned by Task 1's `test_invalid_ranges_raise` and Task 4's `test_changing_surah_clamps_the_ayah_spins`.
5. **Cancel in the picker.** It must leave no edit, no undo step and no dirty state. This is pinned by Task 5's `test_cancel_changes_nothing`.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/qurantext/data/quran_db.py` | + `ayah_range_card(conn, surah_num, from_ayah, to_ayah) -> dict` |
| `src/qurantext/core/video_common.py` | `cards_on_screen` keeps manual cards |
| `src/qurantext/gui/review/session.py` | + `insert_manual_card`, `change_card_ayah`, `is_manual(index)` |
| `src/qurantext/gui/review/ayah_picker.py` (new) | `AyahPicker` dialog |
| `src/qurantext/gui/review/segment_list.py` | ✎ mark; `card_ayah_requested = Signal(int)` on double-click of the Ayah cell and from the context menu |
| `src/qurantext/gui/review/window.py` | toolbar button "Show ayah… from here"; opens the picker; calls the session |
| `src/qurantext/gui/i18n.py` | `ayah_picker.*`, `review.show_ayah*`, `segments.change_ayah`, `session.manual_*` strings |
| Tests | `tests/test_quran_db.py`, `tests/test_video_renderer.py` or `tests/test_export.py`, `tests/test_review_session.py`, `tests/test_review_widgets.py`, `tests/test_review_window.py`, `tests/test_i18n.py` |

---

# Phase 1: data, session and on-screen rule

### Task 1: `ayah_range_card` in the data layer

**Files:**
- Modify: `src/qurantext/data/quran_db.py` (after `surah_ayah_count`, ~line 381)
- Test: `tests/test_quran_db.py`

**Interfaces:**
- Produces: `ayah_range_card(conn: sqlite3.Connection, surah_num: int, from_ayah: int, to_ayah: int) -> dict[str, Any]`. It returns `{"surah_num", "surah_name", "from_ayah", "to_ayah", "text", "full_text"}`. It raises `ValueError` for a surah outside the store, for `from_ayah < 1`, `to_ayah < from_ayah`, or `to_ayah > ayah_count`.

- [ ] **Step 1: Write the failing tests**

Reuse the module's existing fixture that builds or opens a store (read `tests/test_quran_db.py` to find it; there is one built from the bundled text). Then add:

```python
from qurantext.core.arabic import ayah_text_with_marker
from qurantext.data.quran_db import ayah_range_card


def test_a_single_ayah_card_matches_detection(conn):
    card = ayah_range_card(conn, 25, 7, 7)
    raw = conn.execute(
        "SELECT text_raw FROM ayat WHERE surah_num = 25 AND ayah_num = 7"
    ).fetchone()["text_raw"]
    name = conn.execute("SELECT name FROM surahs WHERE surah_num = 25").fetchone()["name"]
    assert card == {
        "surah_num": 25,
        "surah_name": name,
        "from_ayah": 7,
        "to_ayah": 7,
        "text": ayah_text_with_marker(raw, 7),
        "full_text": ayah_text_with_marker(raw, 7),
    }


def test_a_range_joins_ayat_with_newlines_like_detection(conn):
    card = ayah_range_card(conn, 25, 7, 9)
    lines = card["full_text"].split("\n")
    assert len(lines) == 3
    assert lines[0].endswith(" ٧") and lines[2].endswith(" ٩")
    assert card["text"] == card["full_text"]


@pytest.mark.parametrize(
    "surah, start, end", [(0, 1, 1), (115, 1, 1), (25, 0, 1), (25, 9, 7), (25, 1, 78)]
)
def test_invalid_ranges_raise(conn, surah, start, end):
    with pytest.raises(ValueError):
        ayah_range_card(conn, surah, start, end)
```

Al-Furqān has 77 ayat in the shipped Madani counting. If the fixture's store differs, use `surah_ayah_count(conn, 25) + 1` for the last case.

- [ ] **Step 2: Run them to see the failures**

Run: `venv/bin/python -m pytest tests/test_quran_db.py -q -k "ayah_card or range or invalid_ranges"`
Expected: `ImportError: cannot import name 'ayah_range_card'`.

- [ ] **Step 3: Implement**

```python
def ayah_range_card(
    conn: sqlite3.Connection, surah_num: int, from_ayah: int, to_ayah: int
) -> dict[str, Any]:
    """A card's reference and text for ayat *from_ayah*–*to_ayah* of *surah_num*.

    Built exactly as detection builds a lecture card's text (each ayah with its
    number marker, one per line), so a card the person picks by hand reads the
    same as one the matcher found. The text always comes from the store: a card
    names a reference, it never carries typed text.
    """
    count = surah_ayah_count(conn, surah_num)  # raises ValueError for an unknown surah
    if not (1 <= from_ayah <= to_ayah <= count):
        raise ValueError(
            f"Ayat {from_ayah}–{to_ayah} are not in surah {surah_num} (it has {count})."
        )
    name = conn.execute("SELECT name FROM surahs WHERE surah_num = ?", (surah_num,)).fetchone()
    rows = conn.execute(
        "SELECT ayah_num, text_raw FROM ayat WHERE surah_num = ? AND ayah_num BETWEEN ? AND ? "
        "ORDER BY ayah_num",
        (surah_num, from_ayah, to_ayah),
    ).fetchall()
    text = "\n".join(ayah_text_with_marker(r["text_raw"], int(r["ayah_num"])) for r in rows)
    return {
        "surah_num": int(surah_num),
        "surah_name": str(name["name"]),
        "from_ayah": int(from_ayah),
        "to_ayah": int(to_ayah),
        "text": text,
        "full_text": text,
    }
```

Add the needed imports (`ayah_text_with_marker` from `qurantext.core.arabic`, and `Any`) without creating an import cycle: check that `core.arabic` does not import `data.quran_db`. Add the function to `__all__` if the module has one.

- [ ] **Step 4: Run the tests**

Run: `venv/bin/python -m pytest tests/test_quran_db.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/qurantext/data/quran_db.py tests/test_quran_db.py
git commit -m "Build a card's reference and text for any ayah range from the store

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Hand-made cards are always on screen

**Files:**
- Modify: `src/qurantext/core/video_common.py` (`cards_on_screen`, ~line 120)
- Test: `tests/test_video_renderer.py` (rule tests next to the existing `cards_on_screen` tests; find them with `grep -n cards_on_screen tests/*.py`), plus `tests/test_export.py` / `tests/test_preview.py` for the frame-level test

**Interfaces:**
- Consumes: the card dict shape, with the `"manual": True` key.
- Produces: `cards_on_screen(cards, mode, studied_surah=None)` keeps every card whose `manual` is `True`, in lecture mode, under both the automatic and the chosen rule. Manual cards still count toward the automatic "heard longest" guess.

- [ ] **Step 1: Write the failing tests**

Use the module's existing card helper (`_card` in `test_video_renderer.py`, which includes text) to build:

```python
def test_a_manual_card_from_another_surah_is_kept_under_the_automatic_rule():
    cards = [
        _card(25, 7, 0.0, 30.0),
        _card(25, 8, 30.0, 60.0),
        {**_card(2, 255, 60.0, 65.0), "manual": True},
        _card(2, 256, 65.0, 66.0),  # a detected quote from another surah
    ]
    shown = cards_on_screen(cards, "lecture")
    refs = [(c["surah_num"], c["from_ayah"]) for c in shown]
    assert (2, 255) in refs and (2, 256) not in refs


def test_a_manual_card_is_kept_under_a_chosen_surah():
    cards = [_card(25, 7, 0.0, 30.0), {**_card(2, 255, 30.0, 35.0), "manual": True}]
    shown = cards_on_screen(cards, "lecture", studied_surah=25)
    assert [(c["surah_num"], c["from_ayah"]) for c in shown] == [(25, 7), (2, 255)]


def test_manual_cards_still_count_toward_the_automatic_guess():
    cards = [
        _card(25, 7, 0.0, 10.0),
        {**_card(2, 255, 10.0, 60.0), "manual": True},  # heard longest
        _card(25, 8, 60.0, 65.0),
    ]
    shown = cards_on_screen(cards, "lecture")
    # Surah 2 is the guess, so the detected surah-25 cards are hidden; the manual one shows.
    assert [(c["surah_num"], c["from_ayah"]) for c in shown] == [(2, 255)]
```

If `_card`'s signature differs, adapt the calls and keep the meaning. Then add the frame-level test to `tests/test_export.py` (or `tests/test_preview.py`, wherever the existing "export, preview and review agree" test from the studied-surah work lives; reuse its fixture):

```python
def test_a_manual_card_from_another_surah_is_drawn_by_export_and_preview(...):
    # Arrange the existing lecture fixture, then append a card
    #   {**ayah_range_card(conn, 2, 255, 255), "start_time": T, "end_time": T + 3, "manual": True,
    #    "confidence": 1.0, "detected_text": ""}
    # to project.cards, with studied_surah=25 chosen.
    # Assert the card visible at T + 1 in the review session's frame_inputs, in the
    # single-frame preview's result.card, and in the export's on-screen cards is "2:255".
```

Write that test out in full from the existing agreement test, changing only the card list and the asserted reference.

- [ ] **Step 2: Run them to see the failures**

Run: `venv/bin/python -m pytest tests/test_video_renderer.py -q -k manual`
Expected: FAIL; the manual card is filtered out.

- [ ] **Step 3: Implement**

In `cards_on_screen`, after the studied surah is decided (whether chosen or guessed), keep a card when `card.get("manual") is True` **or** when its surah is the studied one or is None. The "heard" totals that feed the automatic guess stay as they are; they already include every countable card, manual ones too. Update the docstring with one sentence: hand-made cards are the person's own choice, so the filter never hides them.

- [ ] **Step 4: Run the tests**

Run: `venv/bin/python -m pytest tests/test_video_renderer.py tests/test_export.py tests/test_preview.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/qurantext/core/video_common.py tests
git commit -m "Never hide a card the person placed by hand behind the studied-surah rule

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Session operations: insert and change

**Files:**
- Modify: `src/qurantext/gui/review/session.py` (next to `set_card_times` / `remove_card`, ~line 544)
- Modify: `src/qurantext/gui/i18n.py` (`session.manual_lecture_only`, in en and ar)
- Test: `tests/test_review_session.py`

**Interfaces:**
- Consumes: `ayah_range_card(conn, surah_num, from_ayah, to_ayah)` (Task 1); `connect` and `QURAN_DB_PATH`.
- Produces:
  - `ReviewSession.insert_manual_card(at: float, surah_num: int, from_ayah: int, to_ayah: int, *, db_path: Path = QURAN_DB_PATH) -> int`, which returns the card's index after sorting.
  - `ReviewSession.change_card_ayah(index: int, surah_num: int, from_ayah: int, to_ayah: int, *, db_path: Path = QURAN_DB_PATH) -> None`.
  - `ReviewSession.is_manual(index: int) -> bool`.
  - Both edits raise `ValueError(t("session.manual_lecture_only"))` in a recitation project, and pass on `ayah_range_card`'s `ValueError`. A failed edit leaves no undo entry and no change.

Timing rules for `insert_manual_card(at, ...)`, where cards are `project.cards` sorted by `start_time`:
1. `at` is clamped to `[0, duration - 0.5]` when `self.duration` is known, otherwise to `>= 0`.
2. If a card starts within 0.05 s of `at` (`abs(start - at) <= 0.05`), do `change_card_ayah` on that card in the same undo step, and return its index.
3. Otherwise:
   - the **next** card is the first with `start_time > at`;
   - `end = next.start_time` if there is one, else `self.duration` if known, else `at + 10.0`;
   - `end = max(end, at + 0.5)`.
4. If a card **contains** `at` (`start < at < end_time`), set its `end_time` to `at`.
5. Build the card as `{**ayah_range_card(...), "start_time": round(at, 3), "end_time": round(end, 3), "confidence": 1.0, "detected_text": "", "manual": True}`, insert it, re-sort by `start_time`, and return its index.

`change_card_ayah` copies the card and keeps `start_time` and `end_time`. It replaces `surah_num`, `surah_name`, `from_ayah`, `to_ayah`, `text` and `full_text` with `ayah_range_card`'s values, and sets `detected_text: ""`, `confidence: 1.0` and `manual: True`. It drops `word_timings` and every key starting with `_matched` or `matched`.

Open the store with `connect(db_path)` inside the method and close it in `finally`. Compute the new card **before** `_before_change()`, so a `ValueError` leaves the undo stack untouched.

- [ ] **Step 1: Write the failing tests**

Add a lecture fixture to `tests/test_review_session.py`, following the existing `session` fixture: a lecture project saved in tmp_path, with cards `25:7` [10, 20] and `25:8` [30, 40] (with text), and `duration = 100.0`. Point `db_path` at the store the test suite already builds; find how `tests/test_quran_db.py` or conftest exposes one. Then add:

```python
def _refs(session):
    return [
        (c["surah_num"], c["from_ayah"], c["to_ayah"], c["start_time"], c["end_time"], bool(c.get("manual")))
        for c in session.project.cards
    ]


def test_insert_between_cards_runs_until_the_next(lecture_session, db):
    i = lecture_session.insert_manual_card(25.0, 25, 7, 7, db_path=db)
    assert _refs(lecture_session)[i] == (25, 7, 7, 25.0, 30.0, True)
    assert lecture_session.dirty and lecture_session.can_undo


def test_insert_inside_a_card_trims_it_and_one_undo_restores_both(lecture_session, db):
    before = _refs(lecture_session)
    lecture_session.insert_manual_card(15.0, 25, 5, 6, db_path=db)
    refs = _refs(lecture_session)
    assert refs[0][4] == 15.0  # 25:7 now ends at the playhead
    assert refs[1] == (25, 5, 6, 15.0, 30.0, True)
    assert lecture_session.undo()
    assert _refs(lecture_session) == before and not lecture_session.dirty


def test_insert_before_the_first_card(lecture_session, db):
    i = lecture_session.insert_manual_card(2.0, 25, 1, 1, db_path=db)
    assert i == 0 and _refs(lecture_session)[0] == (25, 1, 1, 2.0, 10.0, True)


def test_insert_after_the_last_card_runs_to_the_end_of_the_recording(lecture_session, db):
    i = lecture_session.insert_manual_card(50.0, 25, 9, 9, db_path=db)
    assert _refs(lecture_session)[i][3:5] == (50.0, 100.0)


def test_insert_at_the_very_end_still_lasts_half_a_second(lecture_session, db):
    i = lecture_session.insert_manual_card(100.0, 25, 9, 9, db_path=db)
    start, end = _refs(lecture_session)[i][3:5]
    assert start == 99.5 and end == 100.0


def test_insert_without_duration_or_next_card_lasts_ten_seconds(lecture_session, db):
    lecture_session.duration = None
    i = lecture_session.insert_manual_card(50.0, 25, 9, 9, db_path=db)
    assert _refs(lecture_session)[i][3:5] == (50.0, 60.0)


def test_insert_at_a_cards_start_changes_that_card(lecture_session, db):
    i = lecture_session.insert_manual_card(30.03, 2, 255, 255, db_path=db)
    assert len(lecture_session.project.cards) == 2
    assert _refs(lecture_session)[i] == (2, 255, 255, 30.0, 40.0, True)
    assert lecture_session.undo() and not lecture_session.can_undo


def test_change_keeps_times_and_drops_detection_fields(lecture_session, db):
    lecture_session.project.cards[0]["detected_text"] = "قال"
    lecture_session.project.cards[0]["_matched_words"] = 3
    lecture_session.change_card_ayah(0, 25, 3, 4, db_path=db)
    card = lecture_session.project.cards[0]
    assert (card["from_ayah"], card["to_ayah"], card["start_time"], card["end_time"]) == (3, 4, 10, 20)
    assert card["manual"] is True and card["detected_text"] == "" and "_matched_words" not in card
    assert lecture_session.is_manual(0)


def test_invalid_reference_leaves_no_edit(lecture_session, db):
    with pytest.raises(ValueError):
        lecture_session.insert_manual_card(25.0, 25, 9, 7, db_path=db)
    assert not lecture_session.can_undo and not lecture_session.dirty


def test_recitation_projects_refuse_manual_cards(session, db):
    # `session` is the module's existing recitation fixture
    with pytest.raises(ValueError):
        session.insert_manual_card(1.0, 25, 1, 1, db_path=db)
    with pytest.raises(ValueError):
        session.change_card_ayah(0, 25, 1, 1, db_path=db)


def test_a_manual_card_makes_a_render_stale(lecture_session, db):
    lecture_session.project.record_render(Path("v.mp4"), preset=None, basmala_offset_s=0.0)
    lecture_session.insert_manual_card(25.0, 25, 7, 7, db_path=db)
    assert lecture_session.project.render_is_stale
```

- [ ] **Step 2: Run them to see the failures**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_review_session.py -q -k "insert or change or manual or recitation_projects"`
Expected: `AttributeError: 'ReviewSession' object has no attribute 'insert_manual_card'`.

- [ ] **Step 3: Implement**

Follow the timing rules and interfaces above. Write a docstring for each method that says *why* (the teacher goes back to an earlier ayah; detection follows recitation). Add the i18n key `session.manual_lecture_only`:
- en: "Ayah cards can only be placed by hand in a lecture."
- ar: «لا تُضاف بطاقات الآيات يدويًا إلا في الدروس.»

- [ ] **Step 4: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_review_session.py tests/test_i18n.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/qurantext/gui/review/session.py src/qurantext/gui/i18n.py tests/test_review_session.py
git commit -m "Let a lecture review add an ayah card at any moment or change which ayat a card shows

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

**Phase 1 ends here:** one whole-phase review, its fixes, then a local merge after asking the owner.

---

# Phase 2: the picker and the window

### Task 4: `AyahPicker` dialog

**Files:**
- Create: `src/qurantext/gui/review/ayah_picker.py`
- Modify: `src/qurantext/gui/i18n.py` (`ayah_picker.*` in en and ar)
- Test: `tests/test_review_widgets.py`

**Interfaces:**
- Consumes: `ayah_range_card` (Task 1); `connect` and `list_surahs` from `data/quran_db.py`; `surah_label(num, names)` from `gui/surahs.py`; `QURAN_DB_PATH`.
- Produces:
  - `AyahPicker(parent=None, *, surah: int, from_ayah: int = 1, to_ayah: int | None = None, db_path: Path = QURAN_DB_PATH)`, a `QDialog`.
  - `.choice() -> tuple[int, int, int]`, returning `(surah, from_ayah, to_ayah)`.
  - Child widgets the tests can reach: `surah_box: QComboBox` (data = surah number), `from_spin: QSpinBox`, `to_spin: QSpinBox`, `preview: QLabel`, `ok_button: QPushButton`.

Behaviour:
- **Opening the store:**
  - It is opened once in `__init__` to read the surah list and ayah counts, then closed.
  - The preview text is fetched with `ayah_range_card` on each change; it opens and closes its own connection, which is cheap.
  - If the store cannot be opened, the preview shows `t("ayah_picker.no_store")` and `ok_button` is disabled.
- **Surah box:** the 114 surahs, labelled `surah_label`, with the given `surah` selected.
- **Ayah numbers:**
  - The `from_spin` and `to_spin` range is `1..ayah_count(surah)`.
  - Changing the surah clamps both spins to the new count.
  - `to_spin` follows `from_spin` until the person edits `to_spin` directly, and is always at least `from_spin`.
- **Preview:**
  - The text is `ayah_range_card(...)["full_text"]`, right to left.
  - Use the bundled Quran font if `frame_view.py` / `config.paths` exposes one as a Qt font; otherwise the default font.
  - For more than 5 ayat, show the first 5 lines and then `t("ayah_picker.more", count=n - 5)`.
- **Layout:** RTL-safe. The spins are labelled `t("ayah_picker.from")` and `t("ayah_picker.to")`, and the title is `t("ayah_picker.title")`.

i18n keys (en / ar):

| key | en | ar |
|---|---|---|
| `ayah_picker.title` | Choose the ayat for this card | اختر آيات هذه البطاقة |
| `ayah_picker.surah` | Surah | السورة |
| `ayah_picker.from` | From ayah | من الآية |
| `ayah_picker.to` | To ayah | إلى الآية |
| `ayah_picker.more` | …and {count} more | …و{count} أخرى |
| `ayah_picker.no_store` | The Quran text is not ready yet, so no ayah can be chosen. | نص القرآن غير جاهز بعد، فلا يمكن اختيار آية. |

- [ ] **Step 1: Write the failing tests**

```python
from qurantext.gui.review.ayah_picker import AyahPicker


def test_picker_defaults_and_preview(qt_app, db):
    picker = AyahPicker(surah=25, from_ayah=7, db_path=db)
    assert picker.choice() == (25, 7, 7)
    assert picker.preview.text().strip().endswith("٧")


def test_to_follows_from_until_edited(qt_app, db):
    picker = AyahPicker(surah=25, from_ayah=7, db_path=db)
    picker.from_spin.setValue(9)
    assert picker.to_spin.value() == 9
    picker.to_spin.setValue(11)
    picker.from_spin.setValue(10)
    assert picker.choice() == (25, 10, 11)
    picker.from_spin.setValue(12)
    assert picker.to_spin.value() == 12  # never below from


def test_changing_surah_clamps_the_ayah_spins(qt_app, db):
    picker = AyahPicker(surah=2, from_ayah=200, db_path=db)
    index = picker.surah_box.findData(103)  # Al-ʿAṣr: 3 ayat
    picker.surah_box.setCurrentIndex(index)
    assert picker.from_spin.maximum() == 3 and picker.choice()[1:] == (3, 3)


def test_a_long_range_preview_is_shortened(qt_app, db):
    picker = AyahPicker(surah=25, from_ayah=1, to_ayah=20, db_path=db)
    assert picker.preview.text().count("\n") <= 6


def test_no_store_disables_ok(qt_app, tmp_path):
    picker = AyahPicker(surah=25, db_path=tmp_path / "missing.sqlite")
    assert not picker.ok_button.isEnabled()
```

Use the module's `qt_app` helper, and the same `db` store fixture as Task 3. If `qt_app` is not a fixture, use whatever the module calls to get a `QApplication`.

- [ ] **Step 2: Run them to see the failures**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_review_widgets.py -q -k picker`
Expected: `ModuleNotFoundError: qurantext.gui.review.ayah_picker`.

- [ ] **Step 3: Implement**

Follow the behaviour above and the style of the existing review dialogs (`export_dialog.py`): a module docstring that explains why, every string through `t()`, and an RTL-safe layout.

- [ ] **Step 4: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_review_widgets.py tests/test_i18n.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/qurantext/gui/review/ayah_picker.py src/qurantext/gui/i18n.py tests/test_review_widgets.py
git commit -m "Add the ayah picker: a surah, a range, and the exact text the card will show

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Wire it into the review window

**Files:**
- Modify: `src/qurantext/gui/review/window.py` (toolbar ~line 290–309; signal wiring ~line 420)
- Modify: `src/qurantext/gui/review/segment_list.py` (`_fill_row` ~line 101; a new signal; double-click and context menu)
- Modify: `src/qurantext/gui/i18n.py`; `docs/release-checklist.md`
- Test: `tests/test_review_window.py`, `tests/test_review_widgets.py`

**Interfaces:**
- Consumes:
  - `AyahPicker` (Task 4);
  - `ReviewSession.insert_manual_card`, `change_card_ayah`, `is_manual`, `card_at(t)` and `studied_surah` (Task 3, plus the existing ones);
  - the window's current playhead time (find how `_set_start_at_playhead` reads it).
- Produces:
  - `ReviewWindow.show_ayah_button: QPushButton`, labelled `t("review.show_ayah")` with tooltip `t("review.show_ayah.tip")`, and visible only in lecture projects;
  - `SegmentList.card_ayah_requested = Signal(int)`, emitting the card index;
  - a ✎ prefix in the Ayah cell of manual cards;
  - a context-menu action `t("segments.change_ayah")` on card rows in lecture projects.

Behaviour:
- **"Show ayah… from here":** read the playhead time `t0`. The picker's default surah is the surah of the card on screen at `t0` (`session.card_at(t0)`), else `session.studied_surah`, else 1. The default from-ayah is that card's `from_ayah`, else 1.
  - On **OK**: call `session.insert_manual_card(t0, *picker.choice())`, then refresh the views and preview exactly as other card edits do (look at `remove_selected` / `_after_edit`).
  - On a `ValueError`: show the message the way the window shows other session errors.
- **Double-click the Ayah cell, or right-click → "Change ayah…"** on a card row in a lecture project: emit `card_ayah_requested(index)`. The window opens the picker with that card's surah and range, and on OK calls `change_card_ayah(index, ...)`.
- **Cancel** does nothing at all.
- **Recitation projects:** no button and no context-menu entry, and double-click keeps its current behaviour.

i18n keys (en / ar):

| key | en | ar |
|---|---|---|
| `review.show_ayah` | Show ayah… from here | اعرض آية… من هنا |
| `review.show_ayah.tip` | From the playhead on, the card shows the ayat you choose, until the next card. | من موضع التشغيل فصاعدًا تعرض البطاقة الآيات التي تختارها حتى البطاقة التالية. |
| `segments.change_ayah` | Change ayah… | غيّر الآية… |
| `segments.manual` | Placed by hand | وُضعت يدويًا |

`segments.manual` is the tooltip on the ✎ cell. Add every new Arabic string from Tasks 3–5 to the native-speaker review item in `docs/release-checklist.md`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_review_window.py`, build a lecture window with the module's window setup, using the same lecture project as Task 3. Monkeypatch `AyahPicker.exec` to return `QDialog.DialogCode.Accepted` and `AyahPicker.choice` to return a fixed tuple.

```python
def test_show_ayah_is_offered_only_in_lectures(...):
    # lecture window: show_ayah_button visible; recitation window: not visible


def test_show_ayah_inserts_at_the_playhead_and_redraws(...):
    # seek to 25.0, click show_ayah_button with choice (25, 7, 7):
    # project gains a manual 25:7 card at 25.0; the preview frame at 26.0 differs from before;
    # undo_button enabled; one undo removes it


def test_cancel_changes_nothing(...):
    # exec returns Rejected: no card added, not dirty, undo disabled


def test_double_click_and_menu_change_a_cards_ayah(...):
    # emit segment_list.card_ayah_requested(0) (and separately trigger the context-menu action)
    # with choice (2, 255, 255): card 0 becomes 2:255 manual, times unchanged, row shows ✎


def test_a_manual_other_surah_card_shows_in_the_preview_under_a_chosen_surah(...):
    # studied surah set to 25 in the toolbar box; insert a manual 2:255 card; the frame shows it
```

Write these out in full against the module's helpers; each comment above is the exact arrange/act/assert. In `tests/test_review_widgets.py`, add a test that `SegmentList` shows ✎ with the `segments.manual` tooltip for a manual card and none for a detected one.

- [ ] **Step 2: Run them to see the failures**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_review_window.py tests/test_review_widgets.py -q -k "ayah or manual or cancel"`
Expected: `AttributeError: show_ayah_button`.

- [ ] **Step 3: Implement**

Follow the behaviour above. Place the button after the "Surah on the cards" box in the toolbar.

- [ ] **Step 4: Run the suite**

Run `free -m` first, then: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Look at it**

Save offscreen `QWidget.grab()` screenshots to `/tmp/claude-1000/-home-khalil-PycharmProjects-QuranText/ea640bee-253a-4697-9741-210d77dd8806/scratchpad/`:
- `manual-picker.png`: the picker open on Al-Furqān 7–9;
- `manual-window.png`: a lecture window with one ✎ card and its frame;
- `manual-ar.png`: the same window in Arabic.

Look at each one and fix clipping or RTL problems in this task.

- [ ] **Step 6: Commit**

```bash
git add -A src/qurantext/gui tests docs/release-checklist.md
git commit -m "Place or change a lecture's ayah card from the review window

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

**Phase 2 ends here:** one whole-phase review on the most capable model, its fixes, then a local merge after asking the owner.

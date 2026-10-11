# Hand-made ayah cards in lecture projects — design

Date: 2026-10-11 · Status: approved in conversation, awaiting written-spec review

## 1. Purpose

A lecture video shows one ayah card at a time. The card is **latched**: it holds until the next card
starts. Detection follows what the teacher *recites*.

When a teacher reads ayat 7, 8 and 9 and then goes back to explain 7, the video keeps showing 9,
because nothing new was recited. Detecting "the teacher is now talking about 7" is unreliable, so
the person fixes it by hand.

Today the review window can only move a card's times or delete it. This feature lets the person:

- **add** a card at any moment, showing an ayah or a range they pick;
- **change** which ayah or range an existing card shows.

Success means:

- In the review window, the person puts the playhead where the teacher goes back, picks ayah 7, and
  from that moment the preview — and the exported video — show 7 until the next card.
- The ayah text always comes from the bundled Mushaf. The person chooses a reference, never text.
- Hand-made cards survive save, reopen, undo and redo, and look exactly like detected cards in the
  video.

Decisions taken in the brainstorm (the owner's answers):

| Question | Decision |
|---|---|
| One ayah or a range | **Either**: from-ayah and to-ayah, within one surah |
| Hand-made card from a surah other than the studied one | **Always shown**. The studied-surah filter hides only *detected* cards |
| Project types | **Lecture projects only**. Recitation cards follow word timings |

Out of scope:

- editing ayah text;
- hand-made cards in recitations;
- word-level highlighting on lecture cards (they have none today);
- keeping hand-made cards across a re-match whose content changed;
- changes to subtitles. Lecture subtitles are built from the speech captions only (`jobs/export.build_cues`).

## 2. What the person sees (review window, lecture projects)

- A toolbar button **"Show ayah… from here"** opens the **ayah picker** at the playhead's time.
- The **ayah picker** is a small dialog with:
  - **Surah**: the 114 surahs, starting at the surah of the card on screen at the playhead, else the
    studied surah, else Al-Fātiḥa.
  - **From ayah** and **To ayah**: spin boxes limited to the surah's ayah count. To-ayah follows
    from-ayah until the person changes it, and is never below it.
  - **A preview** of the exact card text from the bundled Mushaf, with ayah markers, in the Quran font.
  - **OK** and **Cancel**.
- On OK, a card starts at the playhead and lasts until the next card's start, or the end of the
  recording.
  - If the playhead falls inside an existing card, that card now ends at the playhead.
  - If a card already starts within 0.05 s of the playhead, the picker *changes* that card instead of
    adding one beside it.
  - No card the person places or trims lasts under 0.5 s (amended after the Phase 1 review). A
    playhead in a card's first half second, or less than half a second before the next card starts,
    also changes that card (the nearest start wins), instead of trimming it to a sliver or adding a
    card that flashes. The 0.5 s minimum otherwise applies only at the end of the recording, so a new
    card never overlaps the next one.
- **Change an existing card:** double-click its Ayah cell in the segment list, or right-click → **"Change
  ayah…"**. The picker opens with the card's current surah and range. On OK the card's reference and
  text change; its times stay.
- Hand-made cards are marked **✎** in the Ayah column. A detected card that was changed by hand
  becomes hand-made.
- Hand-made cards can be retimed with the existing time edits, removed, undone and redone, and saved
  like any other card.
- Each add or change is **one undo step**.
- In recitation projects, the button and the menu item are absent.

## 3. Data and rules

### 3.1 The card

A hand-made card is an ordinary lecture card dict:

- `surah_num`, `surah_name` (the store's header name), `from_ayah`, `to_ayah`;
- `start_time`, `end_time` (seconds, rounded to milliseconds);
- `full_text` and `text`: the canonical text of the range, built from the store exactly as detection
  builds it (`core.arabic.ayah_text_with_marker` per ayah, joined with spaces);
- `confidence: 1.0`, `detected_text: ""`;
- **`"manual": true`**.

Changing a detected card copies it, replaces the reference and text fields, drops detection-only
fields that would now be wrong (`detected_text`, `_matched_*`, `word_timings` if any), and sets
`"manual": true`.

### 3.2 Text lookup

A new function, **`ayah_range_card(db_path, surah_num, from_ayah, to_ayah) -> dict`**, lives in the
data layer. It returns the reference and text fields above from the bundled store
(`data/quran_db.py`), the same store detection reads.

- It raises `ValueError` for an invalid surah or range.
- The picker's preview and the session's edit both call it, so the preview always equals the card.

### 3.3 Session operations (`gui/review/session.py`)

- **`insert_manual_card(at: float, surah_num: int, from_ayah: int, to_ayah: int) -> int`** returns the
  new card's index. It follows the timing rules in §2 (trim the card it falls inside, reuse a card
  starting within 0.05 s), and keeps cards sorted by start.
- **`change_card_ayah(index: int, surah_num: int, from_ayah: int, to_ayah: int) -> None`**.
- Both:
  - raise `ValueError` in a recitation project;
  - go through `_before_change`/`_changed`, so undo, the dirty state and the preview behave like
    other edits;
  - change the project's cards, so `content_hash()` marks an existing render stale.

### 3.4 What shows on screen

`video_common.cards_on_screen(cards, mode, studied_surah)` keeps every card with `"manual": true`,
whatever its surah. The studied-surah rule — automatic or chosen — applies to detected cards only.
Manual cards do **not** vote in the automatic "heard longest" guess (amended after the Phase 1
review): a hand-made card lasts until the next card, often minutes of explanation, where a detected
quote lasts only its recitation, so one cross-reference placed by hand would otherwise flip the guess
and hide every detected card of the surah being studied. They are shown regardless, so they need no
vote. A lecture made mostly of hand-made cards is guessed from its detected cards only; the person
can still choose the surah.

The lecture's opening title announces the surah of the first *detected* card that names one, with the
span of that surah's cards (hand-made ones included). Hand-made cards name the surah only when no
detected card does, so a cross-reference placed before the first quote does not retitle the lecture.

The export, the single-frame preview and the review window already share this function, so they
cannot disagree.

### 3.5 Re-matching

Hand-made cards are project content. A re-match whose content is unchanged keeps the project as it
is. A re-match whose content changed replaces the cards; the earlier file stays as the existing
backup. This is the same as any other card edit today.

## 4. Failure handling

| Situation | Behaviour |
|---|---|
| Invalid surah or range reaches the session | `ValueError`; the window shows the message, nothing changes |
| Playhead at or past the end of the recording | The card starts at the last 0.5 s, and lasts at least 0.5 s |
| Range too long for one card | Paged on the card, as recitation ranges already are |
| Store unavailable when the picker opens | The picker shows the existing store error text and OK is disabled |
| Recitation project | The button and menu item are not shown; the session refuses the edit |

## 5. Testing

- `ayah_range_card`:
  - a single ayah and a range, with text equal to what detection would produce;
  - an invalid surah;
  - from-ayah greater than to-ayah;
  - an ayah past the end of the surah.
- `insert_manual_card`:
  - before the first card;
  - inside a card (that card is trimmed);
  - between cards;
  - at the end of the recording;
  - within 0.05 s of a card's start (that card is changed instead);
  - one undo step;
  - the dirty state and stale render.
- `change_card_ayah`:
  - times kept;
  - detection fields dropped;
  - manual flag set;
  - undo.
- `cards_on_screen`: a manual other-surah card is shown, and a detected other-surah card is still
  hidden, under both the automatic and the chosen studied surah.
- Export and preview: a project with a manual card renders that card's text at its time (frame-level
  check).
- GUI (offscreen; pytest-qt is not installed, so the module helpers are used):
  - the toolbar button is present in lecture projects and absent in recitation projects;
  - picker defaults, the to ≥ from rule, and the preview text;
  - OK adds the card, and Cancel changes nothing;
  - double-click and the context menu open the picker for that card;
  - the ✎ mark.
- i18n: every new string in `en` and `ar`. The Arabic strings go on the native-speaker review list.

## 6. Delivery

This builds on the studied-surah feature (`feat/studied-surah`), so it starts after that branch
merges.

It is one branch, `feat/manual-cards`, in its own worktree, delivered in two phases:

1. data, session and on-screen rule;
2. the picker and its wiring in the review window.

Each phase ends with one review, and the branch is merged locally after the second.

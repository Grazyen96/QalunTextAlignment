# UI review fixes — spec

Date: 2026-10-07. Source: a UI/UX review of every Qalun screen (home window in its
empty, filled, running, dark and Arabic states; the review editor light, dark, Arabic
and at a 1000×640 window; the export dialog), rendered offscreen and checked against
the accessibility, interaction, layout, typography and form guidelines.

The app follows the system palette, handles Arabic carefully, shows problems inline and
relies on undo rather than confirmation dialogs. Those stay. What follows is what must
change, grouped by screen. Each item names the behaviour a person must get; the plan
says how.

## Colours (both windows)

1. **Attention amber must read on a light palette.** The fixed amber `(239, 159, 39)`
   used for "Needs review" / "Changed since render" rows and for edited-word markers is
   2.2:1 on a white list background. Text must reach 4.5:1 in a light palette and keep
   ≥ 4.5:1 in a dark one. The colour is chosen from the palette at paint/build time, so a
   theme switch at runtime gets the right one.
2. **Playhead red** must be ≥ 3:1 (non-text) against the window colour in both palettes,
   with margin: ≥ 4.5:1 in a light palette.

## Home window

3. **Job actions are visible.** "Open", "Show in folder" and "Remove from list" are
   buttons under the list, enabled when a job row is current; keyboard users reach them
   with Tab. The right-click menu and double-click/Enter stay.
4. **"More options" rows are labelled** and aligned with the form above: Quran text,
   Output folder, Subtitles, Files. The value texts no longer repeat the label
   ("The certified text that ships with Qalun", not "Quran text: the certified…").
5. **The drop zone shows a drag-over state** while an accepted drag is over it and resets
   when the drag leaves or drops.
6. **Progress is said once.** The form's progress bar hides its own percentage text; the
   status line under it carries the words.
7. **The "from"/"to" range labels are buddies** of their spin boxes.

## Review editor

8. **Toolbar and transport buttons carry tooltips with their shortcut** (Save Ctrl+S,
   Undo Ctrl+Z, Redo Ctrl+Shift+Z, Play Space, −50 ms `,`, +50 ms `.`, with Shift for
   10 ms). Tooltip text goes through `t()` in both languages.
9. **The status-bar shortcut hint fits the window**: it elides to the available width,
   the full text is its tooltip, and it mentions the fine nudge and the ripple drag.
10. **"Zoom" is the slider's buddy.**
11. **"Remove selected" is enabled only while a row is selected.**
12. **The segment list keeps room at laptop sizes.** At a 1000×640 window the list is at
    least 150 px tall; the frame preview shrinks (keeping its aspect ratio) rather than
    forcing the body to its full 480 px.
13. **Word-edge targets are usable.** An edge is grabbed within 8 px (was 5); the strip is
    44 px tall (was 34); the edge under the pointer is highlighted; an edited word shows
    a 3 px amber bar across its top instead of a 5 px dot.
14. **One time format.** The clock, the selection bar, the segment list and the warnings
    strip all show `mm:ss.cc` (the warnings strip with one decimal: `mm:ss.c`).
15. **"Retimed" column header reads "Retimed words".**

## Export dialog

16. **Export is the default button**; Export and Close sit in a button box at the bottom,
    with "Show in folder" beside them once files were written; the result line is above
    the buttons.
17. **The folder field shows the start of the path** (cursor at 0) and carries the full
    path as its tooltip.

## Constraints

- Every user-visible string goes through `t()`/`tn()`, English and Arabic together.
- Tests build widgets offscreen, never touch real settings, never use `QTest.qWait`.
- Attribute names tests already use stay (`detail_label`, `empty_label`, `problem_label`,
  `drop_zone`, `choose_button`, `remove_button`, `selection_bar`, `minus_button`,
  `plus_button`, `_go_button`, `close_button`, `_show_button`, `_result_label`,
  `_video_radio`, `_folder_field`, `_name_field`, `more_button`, `more_group`).

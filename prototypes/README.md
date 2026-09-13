# Prototypes

Throwaway experiments kept because their *result* mattered, not their code.

Nothing here is imported by the package, covered by its tests, or listed in its
dependencies. Each one needs its own environment; the finding it produced says
how to build it.

| Prototype | Question it answered | Finding |
|---|---|---|
| `forced_alignment/` | Can a local CTC aligner time Quran recitation well enough to drive the word highlight? | [docs/findings/forced-alignment-prototype.md](../docs/findings/forced-alignment-prototype.md) — no, not across an elongation, and its confidence score does not reveal that |

Delete a prototype once its finding is acted on and the code no longer adds
anything to the written result.

# Parallel frame rendering: measured, and not worth it yet

**Date:** 13 September 2026
**Plan item:** Phase 5, B4 — render frames in parallel

**Decision: do not. The caching work removed the cost this was aimed at, and the
obvious implementation would be slower than what it replaces.**

## What changed underneath it

B4 was planned when a portrait frame cost about 1 second to draw. Caching the
text layout took that to about 60 milliseconds, and the plan already noted B4 was
only worth doing after B2 "which removes most of the per-frame cost that would
otherwise be parallelised". That turned out to be the whole argument.

Measured on the 13-minute lecture at 1080×1920 and 30 fps, which is the worst
case in the repository:

| | |
|---|---|
| frames | 23,445 |
| distinct renders after event coalescing | 1,319, or 5.6% |
| per render | 55 ms |
| Pillow total | 72 s |
| x264 encode of the same length | 39 s |

Drawing is no longer the dominant cost. It is roughly comparable to encoding,
and the 39 s figure is optimistic because it encodes a black frame; real content
compresses less well.

## Why the obvious implementation would lose

A process pool over the render events has to move the frames it produces. At
1080×1920 a frame is 6.2 MB, and there are 1,319 of them: about 8.2 GB pushed
through inter-process pipes to save 72 s of drawing. Pickling and copying that
is likely to cost more than the work it parallelises.

The implementation that does work is different in kind: split the timeline into
segments, have each worker render *and encode* its own segment to a file, then
concatenate. No frames cross a process boundary, and x264 parallelises too. But
segment boundaries have to land on keyframes, the audio has to be muxed once at
the end rather than per segment, and a failed worker has to clean up its
partial file.

That is a real change to the encoder path for perhaps 2 to 3 times on a job that
now takes about two minutes. The renderer was recently rewritten to stream
frames into one encoder, and this would fragment that again.

## When to revisit

Three things would change the answer:

1. **Longer material.** The 83-minute lecture in `input/` is six times this one.
   At roughly twelve minutes a render, segment-parallel encoding starts to pay.
2. **Higher resolution.** Cost grows with pixels on both halves, and the IPC
   argument gets worse, so the segment design becomes the only option.
3. **A slower per-frame draw.** If a future style costs more to draw — richer
   graphics, more overlays — drawing becomes dominant again.

Until one of those holds, the render is fast enough that the time is better
spent elsewhere.

## Reproducing

Counting render events and timing one costs seconds and needs nothing beyond the
package:

```python
from qurantext.core.frame_renderer import render_frame_pillow
# time render_frame_pillow at the resolution in question, and count the events
# the first pass in write_frame_video would produce for the job.
```

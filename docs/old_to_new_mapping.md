# Old To New Mapping

- `audioAlignment.py` -> `src/qurantext/core/alignment.py`, `src/qurantext/pipelines/recitation.py`
- `fullAyaAlignment.py` -> retired; functionality treated as legacy/deprecated
- `detect_range.py` -> `src/qurantext/pipelines/detection.py`
- `lecture_mode.py` -> `src/qurantext/core/lecture_matching.py`
- `whisperx_service.py` -> `src/qurantext/services/transcription.py`
- `render_ayat_video.py` -> `src/qurantext/core/video_renderer.py`, `src/qurantext/pipelines/video.py`
- `env_utils.py` -> `src/qurantext/config/settings.py`
- root scripts -> thin compatibility wrappers over `src/qurantext/`

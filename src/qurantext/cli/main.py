from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from qurantext import __version__
from qurantext.config.paths import (
    LECTURE_MATCHING_OUTPUT_DIR,
    QURAN_DB_PATH,
    RANGE_MATCHING_OUTPUT_DIR,
    RECITATION_MATCHING_OUTPUT_DIR,
    VIDEOS_OUTPUT_DIR,
    WHISPERX_TRANSCRIPTS_OUTPUT_DIR,
    resolve_quran_path,
)
from qurantext.config.preflight import Status, format_report, prepare_doctor_process, run_checks
from qurantext.config.settings import VIDEO_PRESETS, get_settings
from qurantext.core.coverage import find_uncovered_speech
from qurantext.core.subtitles import SUBTITLE_FORMATS
from qurantext.data.citation_index import DEFAULT_NGRAM_N
from qurantext.data.quran_db import build_quran_db, ensure_quran_db, list_surahs
from qurantext.io.readers import load_json
from qurantext.jobs.export import SUBTITLE_MODES, ExportRequest, export_job
from qurantext.jobs.preview import PreviewRequest, render_preview
from qurantext.jobs.project import Project, load_project, project_path_for, save_project
from qurantext.jobs.project_render import render_project
from qurantext.pipelines.detection import run_detection, run_recitation_range
from qurantext.pipelines.recitation import build_recitation_output_paths, run_word_alignment
from qurantext.pipelines.video import run_video_generation
from qurantext.services.transcription import WhisperXServiceError, transcribe_audio
from qurantext.utils.progress import ConsoleProgress, JobCancelled


def _default_detection_output(
    source_path: str,
    output_dir: str,
    suffix: str,
) -> str:
    source = Path(source_path)
    return str(Path(output_dir) / f"{source.stem}{suffix}")


def _run_word_align(args: argparse.Namespace) -> int:
    whisperx_output = load_json(args.whisperx_json) if args.whisperx_json else None
    output_paths = build_recitation_output_paths(
        args.audio,
        output_dir=args.output_dir,
        base_name=args.base_name,
    )
    result = run_word_alignment(
        resolve_quran_path(args.quran),
        args.audio,
        output_paths=output_paths,
        whisperx_output=whisperx_output,
    )
    print(f"Saved alignment JSON to {result.output_paths.alignment_json}")
    print(f"Saved manual-check JSON to {result.output_paths.manual_check_json}")
    print(f"Saved SRT captions to {result.output_paths.captions_srt}")
    return 0


def _run_detection_mode(args: argparse.Namespace) -> int:
    source_path = args.whisperx_json or args.audio
    output_path = args.output or _default_detection_output(
        source_path,
        args.output_dir,
        args.output_suffix,
    )
    stated = (
        getattr(args, "surah_num", None),
        getattr(args, "from_ayah", None),
        getattr(args, "to_ayah", None),
    )
    if any(v is not None for v in stated):
        if args.mode != "recitation":
            raise SystemExit("--surah-num/--from-ayah/--to-ayah only apply to recitation-match.")
        if not all(v is not None for v in stated):
            raise SystemExit(
                "Give all three of --surah-num, --from-ayah and --to-ayah, or none of them."
            )
        run_recitation_range(
            quran=resolve_quran_path(args.quran),
            output=output_path,
            surah_num=stated[0],
            from_ayah=stated[1],
            to_ayah=stated[2],
            whisperx=args.whisperx_json,
            audio=args.audio,
            max_span=args.max_span,
            echo=True,
        )
        return 0
    run_detection(
        quran=resolve_quran_path(args.quran),
        output=output_path,
        mode=args.mode,
        whisperx=args.whisperx_json,
        audio=args.audio,
        surah=getattr(args, "surah", None),
        head_words=args.head_words,
        tail_words=args.tail_words,
        search_range=args.search_range,
        low_conf=args.low_conf,
        max_span=args.max_span,
        lecture_threshold=args.lecture_threshold,
        min_matched_words=args.min_matched_words,
        echo=True,
    )
    return 0


def _run_transcribe(args: argparse.Namespace) -> int:
    output_path = args.output or _default_detection_output(
        args.audio,
        args.output_dir,
        "_whisperx_raw.json",
    )
    try:
        result = transcribe_audio(args.audio, save_raw_to=output_path, use_cache=not args.no_cache)
    except (FileNotFoundError, WhisperXServiceError) as error:
        raise SystemExit(str(error)) from error
    if result.from_cache:
        print(f"Reused the cached transcript for this audio → {result.raw_output_path}")
    else:
        print(f"Saved WhisperX raw JSON to {result.raw_output_path}")
    print(f"Segments: {result.segment_count}; words: {result.word_count}")
    return 0


def _run_build_db(args: argparse.Namespace) -> int:
    summary = build_quran_db(
        resolve_quran_path(args.quran), args.output, verify=not args.no_verify, ngram_n=args.ngram_n
    )
    print(f"Built Quran store at {summary['db_path']}")
    print(
        f"  surahs={summary['surahs']} ayat={summary['ayat']} words={summary['words']}"
        f" ngrams={summary['ngrams']} data_version={summary['data_version']}"
    )
    return 0


def _resolve_preset(args: argparse.Namespace) -> argparse.Namespace:
    """Resolve width/height/fps on *args* (mutates in place).

    Precedence, applied per dimension:
      1. an explicit ``--preset`` (sets width/height/fps together);
      2. explicit ``--width`` / ``--height`` / ``--fps``;
      3. for a lecture or recitation video render, the portrait ``social``
         preset — such videos are watched on phones, where a portrait frame
         fills the screen without letterboxing;
      4. the configured ``settings.video`` defaults.
    """
    preset = getattr(args, "preset", None)
    if preset is not None:
        args.width, args.height, args.fps = VIDEO_PRESETS[preset]
        return args

    phone_video = getattr(args, "render_video", False) and getattr(args, "mode", None) in (
        "lecture",
        "recitation",
    )
    settings = get_settings()
    if phone_video:
        default_width, default_height, default_fps = VIDEO_PRESETS["social"]
    else:
        default_width = settings.video.width
        default_height = settings.video.height
        default_fps = settings.video.fps

    if args.width is None:
        args.width = default_width
    if args.height is None:
        args.height = default_height
    if args.fps is None:
        args.fps = default_fps
    return args


def _run_surahs(args: argparse.Namespace) -> int:
    """List the surahs, which is what a range picker populates from."""
    conn = ensure_quran_db(resolve_quran_path(args.quran), args.db)
    try:
        rows = list_surahs(conn)
    finally:
        conn.close()
    for row in rows:
        print(f"{row['surah_num']:3d}  {row['name']}  ({row['ayah_count']} ayat)")
    return 0


def _run_check_timing(args: argparse.Namespace) -> int:
    """Report recited audio that no word timing covers."""
    matches = load_json(args.matches)
    words = [
        timing
        for match in (matches.get("matches") or [])
        for timing in (match.get("word_timings") or [])
    ]
    if not words:
        print("This match file carries no word timings, so there is nothing to check against.")
        return 1

    gaps = find_uncovered_speech(
        args.audio, words, min_seconds=args.min_seconds, margin_db=args.margin_db
    )
    total = sum(gap.duration for gap in gaps)
    print(f"Checked {len(words)} word timings against {args.audio}")
    if not gaps:
        print("  Every stretch of speech-level audio is covered by a word.")
        return 0

    print(f"  {len(gaps)} stretch(es) of recitation carry no word, {total:.1f}s in total:")
    for gap in gaps:
        print(f"    {gap.describe()}")
    print(
        "  The highlight holds on the previous word through these. Confirm them by ear "
        "before trusting the timeline."
    )
    return 0


def _run_doctor(args: argparse.Namespace) -> int:
    """Report whether this machine can render, and what to do if not."""
    prepare_doctor_process()
    results = run_checks()
    print(format_report(results))
    return 1 if any(r.status == Status.FAIL for r in results) else 0


def _run_preview(args: argparse.Namespace) -> int:
    """Draw one frame, so a style can be judged without rendering the video."""
    output = args.output or str(Path(args.matches).with_suffix(".preview.png"))
    result = render_preview(
        PreviewRequest(
            matches=Path(args.matches),
            output=Path(output),
            at=args.at,
            preset=args.preset,
            width=args.width,
            height=args.height,
            font_file=Path(args.font_file) if args.font_file else None,
            title=args.title,
            audio=Path(args.audio) if args.audio else None,
        )
    )
    card = result.card or "the opening placeholder"
    print(f"Preview saved to: {result.output}")
    print(f"  {result.width}×{result.height} at {result.at:.2f}s, showing {card}")
    return 0


def _run_project_init(args: argparse.Namespace) -> int:
    project = Project.from_match_file(args.matches, args.audio, mode=getattr(args, "mode", None))
    output = args.output or project_path_for(args.matches)
    path = save_project(project, output)
    print(f"Project saved to: {path}")
    print(f"  mode={project.mode}  cards={len(project.cards)}  captions={len(project.captions)}")
    if project.captions:
        print("  Edit the caption text in this file; renders will use your corrections.")
    return 0


def _run_generate_video(args: argparse.Namespace) -> int:
    project = load_project(args.project) if getattr(args, "project", None) else None
    if project is not None:
        # The project owns the job: its audio and its (possibly corrected)
        # caption cues win over anything re-derived from the match file.
        args.audio = args.audio or str(project.audio)
        args.mode = project.mode
        args.matches = args.matches or (str(project.matches) if project.matches else None)
    if not args.audio or not args.matches:
        raise SystemExit("generate-video needs --audio and --matches, or a --project.")

    _resolve_preset(args)
    output_path = args.output or _default_detection_output(
        args.audio,
        args.output_dir,
        f"_{args.renderer}.mp4",
    )
    subtitles = getattr(args, "subtitles", "burn")
    if subtitles != "burn" and args.renderer != "frame":
        raise SystemExit("--subtitles only applies to the frame renderer.")
    if subtitles == "burn" and args.renderer == "ass":
        run_video_generation(
            audio=args.audio,
            matches=args.matches,
            captions=tuple(project.caption_segments()) if project is not None else None,
            output=output_path,
            preset=getattr(args, "preset", None),
            font_name=args.font_name,
            font_file=args.font_file,
            renderer=args.renderer,
            width=args.width,
            height=args.height,
            fps=args.fps,
            keep_temp=args.keep_temp,
            debug_detected_text=args.debug_detected_text,
            title=getattr(args, "title", None),
            progress=ConsoleProgress(),
        )
    else:
        if project is not None:
            if args.matches and project.matches is None:
                project.matches = Path(args.matches)
            result = render_project(
                project,
                Path(output_path),
                preset=getattr(args, "preset", None),
                subtitles=subtitles,
                formats=tuple(args.subtitle_format),
                width=args.width,
                height=args.height,
                fps=args.fps,
                font_file=Path(args.font_file) if args.font_file else None,
                title=getattr(args, "title", None),
                progress=ConsoleProgress(),
            )
        else:
            result = export_job(
                ExportRequest(
                    audio=Path(args.audio),
                    matches=Path(args.matches),
                    output=Path(output_path),
                    subtitles=subtitles,
                    formats=tuple(args.subtitle_format),
                    preset=getattr(args, "preset", None),
                    width=args.width,
                    height=args.height,
                    fps=args.fps,
                    font_file=Path(args.font_file) if args.font_file else None,
                    title=getattr(args, "title", None),
                ),
                progress=ConsoleProgress(),
            )
        for path in result.subtitles:
            print(f"Subtitles saved to: {path}")
    return 0


def _run_all(args: argparse.Namespace) -> int:
    # Pre-flight: reject incompatible flags BEFORE running any (billed) work.
    if args.render_video and args.mode == "range":
        raise SystemExit("--render-video is only supported for lecture or recitation workflows.")
    _resolve_preset(args)
    default_output_dir = {
        "range": str(RANGE_MATCHING_OUTPUT_DIR),
        "lecture": str(LECTURE_MATCHING_OUTPUT_DIR),
        "recitation": str(RECITATION_MATCHING_OUTPUT_DIR),
    }[args.mode]
    default_suffix = {
        "range": "_range.json",
        "lecture": "_lecture.json",
        "recitation": "_recitation.json",
    }[args.mode]
    output_path = args.output or _default_detection_output(
        args.audio,
        args.output_dir or default_output_dir,
        default_suffix,
    )
    run_detection(
        quran=resolve_quran_path(args.quran),
        output=output_path,
        mode=args.mode,
        audio=args.audio,
        surah=args.surah,
        head_words=args.head_words,
        tail_words=args.tail_words,
        search_range=args.search_range,
        low_conf=args.low_conf,
        max_span=args.max_span,
        lecture_threshold=args.lecture_threshold,
        min_matched_words=args.min_matched_words,
        echo=True,
    )

    if not args.render_video:
        return 0

    video_output = args.video_output or _default_detection_output(
        args.audio,
        args.video_output_dir,
        f"_{args.renderer}.mp4",
    )
    run_video_generation(
        audio=args.audio,
        matches=output_path,
        output=video_output,
        preset=getattr(args, "preset", None),
        font_name=args.font_name,
        font_file=args.font_file,
        renderer=args.renderer,
        width=args.width,
        height=args.height,
        fps=args.fps,
        keep_temp=args.keep_temp,
        debug_detected_text=args.debug_detected_text,
        title=getattr(args, "title", None),
        progress=ConsoleProgress(),
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI parser."""
    settings = get_settings()
    parser = argparse.ArgumentParser(
        prog="qurantext",
        description=("QuranText command-line interface."),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")

    build_db_parser = subparsers.add_parser(
        "build-db",
        help="Build the versioned SQLite store from the certified Qalun text.",
    )
    build_db_parser.add_argument(
        "--quran",
        default=None,
        help="Quran text file. Defaults to the certified Qalun text that ships with the app.",
    )
    build_db_parser.add_argument(
        "--output",
        default=str(QURAN_DB_PATH),
        help="Path for the output SQLite store.",
    )
    build_db_parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip the consistency check against the ayah-level parser.",
    )
    build_db_parser.add_argument(
        "--ngram-n",
        type=int,
        default=DEFAULT_NGRAM_N,
        help="Phrase length for the citation n-gram index.",
    )
    build_db_parser.set_defaults(handler=_run_build_db)

    word_align_parser = subparsers.add_parser(
        "word-align",
        help="Run the legacy word-level recitation alignment workflow.",
    )
    word_align_parser.add_argument(
        "--quran",
        default=None,
        help="Quran text file. Defaults to the one that ships with the app.",
    )
    word_align_parser.add_argument("--audio", required=True, help="Path to the audio file.")
    word_align_parser.add_argument(
        "--whisperx-json",
        help="Optional path to a saved WhisperX JSON response. Skips the API call when provided.",
    )
    word_align_parser.add_argument(
        "--output-dir",
        default=str(RECITATION_MATCHING_OUTPUT_DIR),
        help="Directory where alignment artifacts should be written.",
    )
    word_align_parser.add_argument(
        "--base-name",
        help="Optional output filename stem. Defaults to the audio filename stem.",
    )
    word_align_parser.set_defaults(handler=_run_word_align)

    for command_name, mode, output_dir, output_suffix, help_text in (
        (
            "range-match",
            "range",
            str(RANGE_MATCHING_OUTPUT_DIR),
            "_range.json",
            "Detect the first and last ayah in a transcript.",
        ),
        (
            "lecture-match",
            "lecture",
            str(LECTURE_MATCHING_OUTPUT_DIR),
            "_lecture.json",
            "Detect Quran mentions inside lecture-style audio.",
        ),
        (
            "recitation-match",
            "recitation",
            str(RECITATION_MATCHING_OUTPUT_DIR),
            "_recitation.json",
            "Detect recitation range and timestamped Quran spans.",
        ),
    ):
        subparser = subparsers.add_parser(command_name, help=help_text)
        subparser.add_argument(
            "--quran",
            default=None,
            help="Quran text file. Defaults to the one that ships with the app.",
        )
        source_group = subparser.add_mutually_exclusive_group(required=True)
        source_group.add_argument(
            "--whisperx-json",
            "--whisperx",
            dest="whisperx_json",
            help="Path to an existing WhisperX JSON transcription output.",
        )
        source_group.add_argument(
            "--audio",
            help="Path to an audio file to transcribe with WhisperX via Replicate.",
        )
        subparser.add_argument("--output", help="Explicit path for the output JSON.")
        subparser.add_argument(
            "--output-dir",
            default=output_dir,
            help="Directory where output JSON should be written when --output is omitted.",
        )
        subparser.add_argument(
            "--surah",
            default=None,
            help="Optional surah name to restrict search to. Ignored in lecture mode.",
        )
        subparser.add_argument("--head-words", type=int, default=settings.range_matching.head_words)
        subparser.add_argument("--tail-words", type=int, default=settings.range_matching.tail_words)
        subparser.add_argument(
            "--search-range", type=int, default=settings.range_matching.search_range
        )
        subparser.add_argument("--low-conf", type=float, default=settings.range_matching.low_conf)
        subparser.add_argument("--max-span", type=int, default=settings.lecture_matching.max_span)
        subparser.add_argument(
            "--lecture-threshold", type=float, default=settings.lecture_matching.min_score
        )
        subparser.add_argument(
            "--min-matched-words",
            type=int,
            default=settings.lecture_matching.min_matched_words,
        )
        if mode == "recitation":
            # Stating the range skips detection entirely. Detection cost ~583 s
            # on a 19-minute recitation against 3.7 s here, and covered fewer
            # ayat: it is a search for something the user already knows.
            subparser.add_argument(
                "--surah-num",
                type=int,
                default=None,
                help="Surah number (1-114). With --from-ayah and --to-ayah, skips detection.",
            )
            subparser.add_argument("--from-ayah", type=int, default=None)
            subparser.add_argument("--to-ayah", type=int, default=None)
        subparser.set_defaults(
            handler=_run_detection_mode,
            mode=mode,
            output_suffix=output_suffix,
        )

    transcribe_parser = subparsers.add_parser(
        "transcribe",
        help="Run WhisperX transcription and save the raw JSON output.",
    )
    transcribe_parser.add_argument("--audio", required=True, help="Path to the audio file.")
    transcribe_parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Transcribe again even if this audio has been transcribed before.",
    )
    transcribe_parser.add_argument("--output", help="Explicit path for the raw WhisperX JSON.")
    transcribe_parser.add_argument(
        "--output-dir",
        default=str(WHISPERX_TRANSCRIPTS_OUTPUT_DIR),
        help="Directory where raw WhisperX JSON should be written when --output is omitted.",
    )
    transcribe_parser.set_defaults(handler=_run_transcribe)

    video_parser = subparsers.add_parser(
        "generate-video",
        help="Render an MP4 from lecture or recitation match results.",
    )
    video_parser.add_argument("--audio", default=None, help="Path to the original audio file.")
    video_parser.add_argument("--matches", default=None, help="Path to the match JSON result file.")
    video_parser.add_argument(
        "--project",
        default=None,
        help=(
            "Render from a project file. Its caption cues are used verbatim, so "
            "corrections made there survive the render."
        ),
    )
    video_parser.add_argument("--output", help="Explicit path for the output MP4 video.")
    video_parser.add_argument(
        "--output-dir",
        default=str(VIDEOS_OUTPUT_DIR),
        help="Directory where the output MP4 should be written when --output is omitted.",
    )
    video_parser.add_argument("--font-name", default=None)
    video_parser.add_argument("--font-file", default=None)
    video_parser.add_argument(
        "--title",
        default=None,
        help="Centre placeholder text shown before the first ayah (frame renderer).",
    )
    video_parser.add_argument(
        "--renderer", choices=["ass", "frame"], default=settings.video.renderer
    )
    video_parser.add_argument(
        "--preset",
        choices=sorted(VIDEO_PRESETS),
        default=None,
        help=(
            "Named quality preset that sets width, height and fps together. "
            "Overrides --width / --height / --fps when specified. "
            "Choices: "
            + ", ".join(f"{k} ({v[0]}x{v[1]}@{v[2]}fps)" for k, v in sorted(VIDEO_PRESETS.items()))
        ),
    )
    video_parser.add_argument("--width", type=int, default=None)
    video_parser.add_argument("--height", type=int, default=None)
    video_parser.add_argument("--fps", type=int, default=None)
    video_parser.add_argument(
        "--subtitles",
        choices=list(SUBTITLE_MODES),
        default="burn",
        help=(
            "burn: subtitles in the picture. sidecar: a clean video plus subtitle "
            "files. both: the usual answer for publishing."
        ),
    )
    video_parser.add_argument(
        "--subtitle-format",
        nargs="+",
        choices=list(SUBTITLE_FORMATS),
        default=["srt"],
        help="Formats to write alongside the video when subtitles are not burned in.",
    )
    video_parser.add_argument("--keep-temp", action="store_true")
    video_parser.add_argument("--debug-detected-text", action="store_true")
    video_parser.set_defaults(handler=_run_generate_video)

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check that this machine can render, and say what to do if not.",
    )
    doctor_parser.set_defaults(handler=_run_doctor)

    preview_parser = subparsers.add_parser(
        "preview",
        help="Render one frame to a PNG, to judge a style without rendering the video.",
    )
    preview_parser.add_argument(
        "--matches", required=True, help="Path to the match JSON result file."
    )
    preview_parser.add_argument("--output", help="Path for the PNG. Defaults beside the matches.")
    preview_parser.add_argument(
        "--at",
        type=float,
        default=None,
        help="Seconds into the video. Defaults to halfway through the first card.",
    )
    preview_parser.add_argument("--audio", default=None, help="Optional, to clamp --at.")
    preview_parser.add_argument("--preset", choices=sorted(VIDEO_PRESETS), default=None)
    preview_parser.add_argument("--width", type=int, default=None)
    preview_parser.add_argument("--height", type=int, default=None)
    preview_parser.add_argument("--font-file", default=None)
    preview_parser.add_argument("--title", default=None)
    preview_parser.set_defaults(handler=_run_preview)

    surahs_parser = subparsers.add_parser(
        "surahs",
        help="List surahs and their ayah counts (the range picker's data).",
    )
    surahs_parser.add_argument(
        "--quran",
        default=None,
        help="Quran text file. Defaults to the one that ships with the app.",
    )
    surahs_parser.add_argument(
        "--db", default=str(QURAN_DB_PATH), help="Path to the SQLite Quran store."
    )
    surahs_parser.set_defaults(handler=_run_surahs)

    check_parser = subparsers.add_parser(
        "check-timing",
        help="Find recited audio that no word timing covers.",
    )
    check_parser.add_argument("--audio", required=True, help="Path to the original audio file.")
    check_parser.add_argument(
        "--matches", required=True, help="Path to a match JSON result carrying word timings."
    )
    check_parser.add_argument(
        "--min-seconds",
        type=float,
        default=1.5,
        help="Ignore shorter stretches; below this they are breaths and word junctures.",
    )
    check_parser.add_argument(
        "--margin-db",
        type=float,
        default=8.0,
        help="How far above the clip's noise floor a frame must sit to count as speech.",
    )
    check_parser.set_defaults(handler=_run_check_timing)

    project_parser = subparsers.add_parser(
        "project",
        help="Create a project file that owns a job's cards and editable captions.",
    )
    project_sub = project_parser.add_subparsers(dest="project_command")
    project_init = project_sub.add_parser(
        "init",
        help="Derive a project from a match result so its captions can be corrected.",
    )
    project_init.add_argument("--audio", required=True, help="Path to the original audio file.")
    project_init.add_argument(
        "--matches", required=True, help="Path to the match JSON result file."
    )
    project_init.add_argument(
        "--mode",
        default=None,
        choices=["lecture", "recitation"],
        help="Override the mode recorded in the match file's metadata.",
    )
    project_init.add_argument(
        "--output",
        default=None,
        help=(
            "Path for the project file. Defaults to the match file's name with "
            ".qalun.json, beside it, which is where the app looks for jobs."
        ),
    )
    project_init.set_defaults(handler=_run_project_init)
    project_parser.set_defaults(
        handler=lambda _args: project_parser.print_help() or 0,
        project_command=None,
    )

    run_all_parser = subparsers.add_parser(
        "run-all",
        help="Run audio transcription plus Quran matching, with optional video rendering.",
    )
    run_all_parser.add_argument(
        "--quran",
        default=None,
        help="Quran text file. Defaults to the one that ships with the app.",
    )
    run_all_parser.add_argument("--audio", required=True, help="Path to the audio file.")
    run_all_parser.add_argument(
        "--mode",
        choices=["range", "lecture", "recitation"],
        default="recitation",
        help="Which end-to-end matching workflow to run.",
    )
    run_all_parser.add_argument("--output", help="Explicit path for the detection JSON output.")
    run_all_parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory where detection JSON should be written when --output is omitted.",
    )
    run_all_parser.add_argument("--surah", default=None)
    run_all_parser.add_argument(
        "--head-words", type=int, default=settings.range_matching.head_words
    )
    run_all_parser.add_argument(
        "--tail-words", type=int, default=settings.range_matching.tail_words
    )
    run_all_parser.add_argument(
        "--search-range", type=int, default=settings.range_matching.search_range
    )
    run_all_parser.add_argument("--low-conf", type=float, default=settings.range_matching.low_conf)
    run_all_parser.add_argument("--max-span", type=int, default=settings.lecture_matching.max_span)
    run_all_parser.add_argument(
        "--lecture-threshold", type=float, default=settings.lecture_matching.min_score
    )
    run_all_parser.add_argument(
        "--min-matched-words",
        type=int,
        default=settings.lecture_matching.min_matched_words,
    )
    run_all_parser.add_argument(
        "--render-video",
        action="store_true",
        help="Render a video after matching completes. Only valid for lecture or recitation mode.",
    )
    run_all_parser.add_argument("--video-output", help="Explicit path for the rendered video.")
    run_all_parser.add_argument(
        "--video-output-dir",
        default=str(VIDEOS_OUTPUT_DIR),
        help="Directory where the video should be written when --video-output is omitted.",
    )
    run_all_parser.add_argument("--font-name", default=None)
    run_all_parser.add_argument("--font-file", default=None)
    run_all_parser.add_argument(
        "--title",
        default=None,
        help="Centre placeholder text shown before the first ayah (frame renderer).",
    )
    run_all_parser.add_argument(
        "--renderer", choices=["ass", "frame"], default=settings.video.renderer
    )
    run_all_parser.add_argument(
        "--preset",
        choices=sorted(VIDEO_PRESETS),
        default=None,
        help=(
            "Named quality preset that sets width, height and fps together. "
            "Overrides --width / --height / --fps when specified."
        ),
    )
    run_all_parser.add_argument("--width", type=int, default=None)
    run_all_parser.add_argument("--height", type=int, default=None)
    run_all_parser.add_argument("--fps", type=int, default=None)
    run_all_parser.add_argument("--keep-temp", action="store_true")
    run_all_parser.add_argument("--debug-detected-text", action="store_true")
    run_all_parser.set_defaults(handler=_run_all)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the QuranText CLI."""
    try:
        parser = build_parser()
    except ValueError as error:
        # e.g. a malformed QURANTEXT_* env override; report cleanly instead of
        # crashing before argparse (which would break even `--help`).
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    try:
        return args.handler(args)
    except JobCancelled as error:
        print(f"Cancelled: {error}", file=sys.stderr)
        return 130
    except (FileNotFoundError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        # WhisperXServiceError is a RuntimeError; json.JSONDecodeError is a
        # ValueError — both are covered. SystemExit (used for pre-flight guards)
        # is not an Exception, so it propagates with its own message/exit code.
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

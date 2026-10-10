import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from qurantext.cli.main import build_parser


def test_cli_parser_includes_expected_commands() -> None:
    parser = build_parser()
    help_text = parser.format_help()
    assert "range-match" in help_text
    assert "lecture-match" in help_text
    assert "recitation-match" in help_text
    assert "generate-video" in help_text
    assert "run-all" in help_text


def test_package_and_root_detect_range_smoke(tmp_path: Path) -> None:
    quran = tmp_path / "sample_quran.txt"
    whisper = tmp_path / "sample_whisper.json"
    output = tmp_path / "result.json"

    quran.write_text(
        "سُورَةُ الفَاتِحَةِ\nالْحَمْدُ لِلَّهِ رَبِّ الْعَالَمِينَ ١\nالرَّحْمَنِ الرَّحِيمِ ٢\n",
        encoding="utf-8",
    )
    whisper.write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "words": [
                            {"word": "الْحَمْدُ", "start": 0.0, "end": 0.3},
                            {"word": "لِلَّهِ", "start": 0.3, "end": 0.6},
                            {"word": "رَبِّ", "start": 0.6, "end": 0.8},
                            {"word": "الْعَالَمِينَ", "start": 0.8, "end": 1.2},
                            {"word": "الرَّحْمَنِ", "start": 1.2, "end": 1.5},
                            {"word": "الرَّحِيمِ", "start": 1.5, "end": 1.8},
                        ]
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = "src"

    subprocess.run(
        [
            sys.executable,
            "-m",
            "qurantext",
            "range-match",
            "--quran",
            str(quran),
            "--whisperx-json",
            str(whisper),
            "--output",
            str(output),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        check=True,
    )

    package_result = json.loads(output.read_text(encoding="utf-8"))
    assert package_result["first_ayah"]["ayah_num"] == 1
    # No transcription ran, so the file says no engine produced it.
    assert package_result["meta"]["transcription_engine"] is None

    subprocess.run(
        [
            sys.executable,
            "detect_range.py",
            "--quran",
            str(quran),
            "--whisperx",
            str(whisper),
            "--output",
            str(output),
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
    )

    wrapper_result = json.loads(output.read_text(encoding="utf-8"))
    assert wrapper_result["last_ayah"]["ayah_num"] == 2


def test_cli_offers_the_engine_choice(capsys) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["transcribe", "--help"])
    out = capsys.readouterr().out
    assert "--engine" in out and "local" in out and "whisperx" in out


@pytest.mark.parametrize(
    ("argv", "target"),
    [
        (["transcribe", "--audio", "a.wav"], "transcribe_audio"),
        (["word-align", "--audio", "a.wav"], "run_word_alignment"),
        (["range-match", "--audio", "a.wav"], "run_detection"),
        (["lecture-match", "--audio", "a.wav"], "run_detection"),
        (["recitation-match", "--audio", "a.wav"], "run_detection"),
        (
            [
                "recitation-match",
                "--audio",
                "a.wav",
                "--surah-num",
                "1",
                "--from-ayah",
                "1",
                "--to-ayah",
                "2",
            ],
            "run_recitation_range",
        ),
        (["run-all", "--audio", "a.wav", "--mode", "lecture"], "run_detection"),
    ],
)
def test_the_cli_passes_the_engine_choice_down(monkeypatch, argv, target) -> None:
    from qurantext.cli import main as cli_main
    from qurantext.services.errors import TranscriptionError

    seen = {}

    def stub(*_args, **kwargs):
        seen.update(kwargs)
        raise TranscriptionError("stub reached")

    for name in ("run_detection", "run_recitation_range", "run_word_alignment", "transcribe_audio"):
        monkeypatch.setattr(cli_main, name, stub)

    def run(args):
        try:
            return cli_main.main(args)
        except SystemExit as exit_:  # `transcribe` reports its error this way
            return exit_.code

    assert run([*argv, "--engine", "local"]) not in (0, None)
    assert seen["engine"] == "local"
    seen.clear()
    run(argv)
    assert seen["engine"] is None
    if target in ("transcribe_audio", "run_word_alignment"):
        assert isinstance(seen["progress"], cli_main.ConsoleProgress)

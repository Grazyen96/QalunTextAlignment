import json
import os
import subprocess
import sys
from pathlib import Path

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

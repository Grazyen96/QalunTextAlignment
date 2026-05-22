from pathlib import Path

from qurantext.core.quran_parser import parse_ayat


def test_parse_ayat_skips_basmala_and_reads_numbers_after_text(tmp_path: Path) -> None:
    quran_file = tmp_path / "sample_quran.txt"
    quran_file.write_text(
        "سُورَةُ الفَاتِحَةِ\nبِسْمِ اللَّهِ الرَّحْمَنِ الرَّحِيمِ\nالْحَمْدُ لِلَّهِ رَبِّ الْعَالَمِينَ ١\nالرَّحْمَنِ الرَّحِيمِ ٢\n",
        encoding="utf-8",
    )

    ayat = parse_ayat(quran_file)

    assert [ayah["ayah_num"] for ayah in ayat] == [1, 2]
    assert ayat[0]["text_raw"] == "الْحَمْدُ لِلَّهِ رَبِّ الْعَالَمِينَ"
    assert ayat[1]["text_norm"] == "الرحمن الرحيم"


def test_parse_ayat_respects_surah_filter(tmp_path: Path) -> None:
    quran_file = tmp_path / "two_surahs.txt"
    quran_file.write_text(
        "سُورَةُ الفَاتِحَةِ\nالْحَمْدُ لِلَّهِ رَبِّ الْعَالَمِينَ ١\nسُورَةُ الإِخْلَاصِ\nقُلْ هُوَ اللَّهُ أَحَدٌ ١\n",
        encoding="utf-8",
    )

    ayat = parse_ayat(quran_file, surah_filter="الإخلاص")

    assert len(ayat) == 1
    assert ayat[0]["surah_num"] == 2
    assert ayat[0]["ayah_num"] == 1

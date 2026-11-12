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


def test_a_zero_padded_version_number_is_not_an_ayah_marker(tmp_path: Path) -> None:
    """KFGQPC's Ver05 file ended in an attribution footer with «النسخة رقم ٠٥».

    Read as a marker it flushed the footer as a phantom An-Nās ayah 5. The v10
    file Qalun ships has no footer, so this keeps the rule covered on its own.
    """
    quran_file = tmp_path / "with_footer.txt"
    quran_file.write_text(
        "سُورَةُ النَّاسِ\nقُلْ أَعُوذُ بِرَبِّ اِ۬لنَّاسِ ١\n\n78\n"
        "خط النسخ الحاسوبي ـ قالون ـ مجمع الملك فهد لطباعة المصحف الشريف ـ النسخة رقم ٠٥\n",
        encoding="utf-8",
    )

    ayat = parse_ayat(quran_file)

    assert [ayah["ayah_num"] for ayah in ayat] == [1]
    assert "الشريف" not in ayat[0]["text_norm"]

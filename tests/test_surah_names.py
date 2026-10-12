"""Surah names as a generated intro writes them: the store's spelling in plain letters.

The store spells each name with its vowel marks («سُورَةُ آلِ عِمْرَانَ»). A title
drops them, but some marks are part of a letter (the madda of «آل»), and a final
yeh carrying a dagger alef is an alef maksura («الشورى»). The 114 names below are
the reviewed expectation; a change to the store or to the rules shows here.
"""

from __future__ import annotations

import pytest

from qurantext.core.arabic import plain_surah_name, surah_title
from qurantext.data.quran_db import stored_surah_names

#: Every surah's title, read and checked (2026-10-12). 34 «سبإ» and 78 «النبإ» keep the
#: store's Uthmani hamza; most people write «سبأ» and «النبأ» (on the native-speaker list).
PLAIN_TITLES = {
    1: "سورة الفاتحة",
    2: "سورة البقرة",
    3: "سورة آل عمران",
    4: "سورة النساء",
    5: "سورة المائدة",
    6: "سورة الأنعام",
    7: "سورة الأعراف",
    8: "سورة الأنفال",
    9: "سورة التوبة",
    10: "سورة يونس",
    11: "سورة هود",
    12: "سورة يوسف",
    13: "سورة الرعد",
    14: "سورة إبراهيم",
    15: "سورة الحجر",
    16: "سورة النحل",
    17: "سورة الإسراء",
    18: "سورة الكهف",
    19: "سورة مريم",
    20: "سورة طه",
    21: "سورة الأنبياء",
    22: "سورة الحج",
    23: "سورة المؤمنون",
    24: "سورة النور",
    25: "سورة الفرقان",
    26: "سورة الشعراء",
    27: "سورة النمل",
    28: "سورة القصص",
    29: "سورة العنكبوت",
    30: "سورة الروم",
    31: "سورة لقمان",
    32: "سورة السجدة",
    33: "سورة الأحزاب",
    34: "سورة سبإ",
    35: "سورة فاطر",
    36: "سورة يس",
    37: "سورة الصافات",
    38: "سورة ص",
    39: "سورة الزمر",
    40: "سورة غافر",
    41: "سورة فصلت",
    42: "سورة الشورى",
    43: "سورة الزخرف",
    44: "سورة الدخان",
    45: "سورة الجاثية",
    46: "سورة الأحقاف",
    47: "سورة محمد",
    48: "سورة الفتح",
    49: "سورة الحجرات",
    50: "سورة ق",
    51: "سورة الذاريات",
    52: "سورة الطور",
    53: "سورة النجم",
    54: "سورة القمر",
    55: "سورة الرحمن",
    56: "سورة الواقعة",
    57: "سورة الحديد",
    58: "سورة المجادلة",
    59: "سورة الحشر",
    60: "سورة الممتحنة",
    61: "سورة الصف",
    62: "سورة الجمعة",
    63: "سورة المنافقون",
    64: "سورة التغابن",
    65: "سورة الطلاق",
    66: "سورة التحريم",
    67: "سورة الملك",
    68: "سورة القلم",
    69: "سورة الحاقة",
    70: "سورة المعارج",
    71: "سورة نوح",
    72: "سورة الجن",
    73: "سورة المزمل",
    74: "سورة المدثر",
    75: "سورة القيامة",
    76: "سورة الإنسان",
    77: "سورة المرسلات",
    78: "سورة النبإ",
    79: "سورة النازعات",
    80: "سورة عبس",
    81: "سورة التكوير",
    82: "سورة الانفطار",
    83: "سورة المطففين",
    84: "سورة الانشقاق",
    85: "سورة البروج",
    86: "سورة الطارق",
    87: "سورة الأعلى",
    88: "سورة الغاشية",
    89: "سورة الفجر",
    90: "سورة البلد",
    91: "سورة الشمس",
    92: "سورة الليل",
    93: "سورة الضحى",
    94: "سورة الشرح",
    95: "سورة التين",
    96: "سورة العلق",
    97: "سورة القدر",
    98: "سورة البينة",
    99: "سورة الزلزلة",
    100: "سورة العاديات",
    101: "سورة القارعة",
    102: "سورة التكاثر",
    103: "سورة العصر",
    104: "سورة الهمزة",
    105: "سورة الفيل",
    106: "سورة قريش",
    107: "سورة الماعون",
    108: "سورة الكوثر",
    109: "سورة الكافرون",
    110: "سورة النصر",
    111: "سورة المسد",
    112: "سورة الإخلاص",
    113: "سورة الفلق",
    114: "سورة الناس",
}


def test_every_surah_name_reads_as_reviewed(store):
    names = stored_surah_names(store)
    assert len(names) == 114
    assert {number: surah_title(name) for number, name in names.items()} == PLAIN_TITLES


@pytest.mark.parametrize(
    ("number", "title"),
    [
        (3, "سورة آل عمران"),  # alef + madda is one letter, not «ال»
        (21, "سورة الأنبياء"),  # the store's yeh + hamza is not composed into «ئ»
        (42, "سورة الشورى"),  # a final «يٰ» is «ى»
        (55, "سورة الرحمن"),  # a dagger alef inside a word just goes
        (87, "سورة الأعلى"),
        (93, "سورة الضحى"),
        (36, "سورة يس"),  # the madda over a lone letter goes
    ],
)
def test_the_names_a_mark_used_to_misspell(store, number, title):
    assert surah_title(stored_surah_names(store)[number]) == title


def test_the_rules_on_their_own():
    assert plain_surah_name("سُورَةُ آلِ عِمْرَانَ") == "سورة آل عمران"
    assert plain_surah_name("ٱلْأَعْلَيٰ") == "ٱلأعلى"  # only marks go; letters stay
    assert plain_surah_name("الضُّحَىٰ") == "الضحى"
    assert plain_surah_name("مُوسَيٰ وَعِيسَيٰ") == "موسى وعيسى", "each word's own end"
    # The store writes yeh + hamza above (U+064A U+0654), not the letter «ئ».
    assert plain_surah_name("الْأَنبِ\u064a\u0654َاءِ") == "الأنبياء"
    assert plain_surah_name("الرَّحْمَٰن") == "الرحمن"
    assert plain_surah_name("سـورة   الفرقان") == "سورة الفرقان", "tatweel and spaces"
    assert surah_title("الفرقان") == "سورة الفرقان"
    assert surah_title("سُورَةُ الفُرقَانِ") == "سورة الفرقان", "never «سورة» twice"
    assert surah_title("  ") == ""

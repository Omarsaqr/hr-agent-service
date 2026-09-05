import re
from datetime import date

from app.domain.models import Language

_ARABIC_INDIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_ARABIC_SCRIPT_RE = re.compile(r"[؀-ۿ]")

_HIJRI_MONTH_NAMES_AR = [
    "محرم",
    "صفر",
    "ربيع الأول",
    "ربيع الآخر",
    "جمادى الأولى",
    "جمادى الآخرة",
    "رجب",
    "شعبان",
    "رمضان",
    "شوال",
    "ذو القعدة",
    "ذو الحجة",
]

# Civil (Friday) tabular epoch as a Julian Day Number. Verified against
# two independently-sourced Hijri new-year dates (1446 AH = 2024-07-07,
# 1447 AH = 2025-06-26) rather than taken from memory -- the commonly
# quoted epoch constant (1948440) is off by one day against both.
_HIJRI_EPOCH_JDN = 1948439


def _gregorian_to_jdn(d: date) -> int:
    a = (14 - d.month) // 12
    y = d.year + 4800 - a
    m = d.month + 12 * a - 3
    return d.day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045


def gregorian_to_hijri(d: date) -> tuple[int, int, int]:
    """Tabular (arithmetic) Hijri (year, month, day) -- not moon-sighting
    based, so it can differ from an official calendar (Umm al-Qura, or
    local sighting) by a day or two. Good enough to show a Hijri
    equivalent alongside a Gregorian date; not authoritative for a date
    that must match a real announced calendar.
    """
    jdn = _gregorian_to_jdn(d)
    ell = jdn - _HIJRI_EPOCH_JDN + 10632
    n = (ell - 1) // 10631
    ell = ell - 10631 * n + 354
    j = ((10985 - ell) // 5316) * ((50 * ell) // 17719) + (ell // 5670) * ((43 * ell) // 15238)
    ell = ell - ((30 - j) // 15) * ((17719 * j) // 50) - (j // 16) * ((15238 * j) // 43) + 29
    month = (24 * ell) // 709
    day = ell - (709 * month) // 24
    year = 30 * n + j - 30
    return year, month, day


def to_arabic_indic_numerals(text: str) -> str:
    return "".join(_ARABIC_INDIC_DIGITS[int(ch)] if ch.isdigit() else ch for ch in text)


def format_date_bilingual(d: date, language: Language) -> str:
    gregorian_str = d.strftime("%Y-%m-%d")
    if language == "en":
        return gregorian_str

    hijri_year, hijri_month, hijri_day = gregorian_to_hijri(d)
    hijri_str = f"{hijri_day} {_HIJRI_MONTH_NAMES_AR[hijri_month - 1]} {hijri_year}هـ"
    return to_arabic_indic_numerals(f"{gregorian_str} (الموافق {hijri_str})")


def detect_script(text: str) -> Language | None:
    if _ARABIC_SCRIPT_RE.search(text):
        return "ar"
    return "en" if text.strip() else None


def resolve_language(
    employee_preferred: Language | None, detected_script: Language | None
) -> Language:
    """Detected script (from the incoming message) overrides the
    employee's profile default for this reply, per the brief; if
    neither is known, default to English rather than guessing.
    """
    return detected_script or employee_preferred or "en"


def text_direction(language: Language) -> str:
    # RTL layout is the web widget's job (a `dir` attribute), not
    # something this backend renders -- this just hands it the fact.
    return "rtl" if language == "ar" else "ltr"

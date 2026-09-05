from datetime import date

from app.core.i18n import (
    detect_script,
    format_date_bilingual,
    gregorian_to_hijri,
    resolve_language,
    text_direction,
    to_arabic_indic_numerals,
)


def test_gregorian_to_hijri_matches_a_verified_new_year_date_1447() -> None:
    # 1 Muharram 1447 AH = Thursday, 2025-06-26 (independently sourced).
    assert gregorian_to_hijri(date(2025, 6, 26)) == (1447, 1, 1)


def test_gregorian_to_hijri_matches_a_verified_new_year_date_1446() -> None:
    # 1 Muharram 1446 AH = Sunday, 2024-07-07 (independently sourced).
    assert gregorian_to_hijri(date(2024, 7, 7)) == (1446, 1, 1)


def test_gregorian_to_hijri_advances_a_day_correctly() -> None:
    year, month, day = gregorian_to_hijri(date(2025, 6, 27))
    assert (year, month, day) == (1447, 1, 2)


def test_to_arabic_indic_numerals_converts_digits_only() -> None:
    assert to_arabic_indic_numerals("2026-06-01") == "٢٠٢٦-٠٦-٠١"


def test_to_arabic_indic_numerals_leaves_non_digits_untouched() -> None:
    assert to_arabic_indic_numerals("5 days") == "٥ days"


def test_format_date_bilingual_english_is_plain_gregorian() -> None:
    assert format_date_bilingual(date(2026, 6, 1), "en") == "2026-06-01"


def test_format_date_bilingual_arabic_includes_hijri_equivalent() -> None:
    result = format_date_bilingual(date(2025, 6, 26), "ar")

    assert "١٤٤٧" in result  # Hijri year, Arabic-Indic
    assert "محرم" in result  # Hijri month name
    assert "٢٠٢٥" in result  # Gregorian year, still shown


def test_detect_script_arabic_text() -> None:
    assert detect_script("مرحبا") == "ar"


def test_detect_script_english_text() -> None:
    assert detect_script("hello") == "en"


def test_detect_script_empty_text_is_unknown() -> None:
    assert detect_script("   ") is None


def test_detect_script_mixed_text_treated_as_arabic() -> None:
    # Any Arabic-script character present is enough to route the reply
    # in Arabic -- the brief is explicit that mixed input resolves to
    # one language rather than interleaving.
    assert detect_script("hello مرحبا") == "ar"


def test_resolve_language_prefers_detected_script_over_profile() -> None:
    assert resolve_language(employee_preferred="en", detected_script="ar") == "ar"


def test_resolve_language_falls_back_to_profile_when_script_unknown() -> None:
    assert resolve_language(employee_preferred="ar", detected_script=None) == "ar"


def test_resolve_language_defaults_to_english_when_nothing_is_known() -> None:
    assert resolve_language(employee_preferred=None, detected_script=None) == "en"


def test_text_direction_arabic_is_rtl() -> None:
    assert text_direction("ar") == "rtl"


def test_text_direction_english_is_ltr() -> None:
    assert text_direction("en") == "ltr"

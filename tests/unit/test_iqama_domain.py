from datetime import date

from app.domain.iqama import days_until_expiry, needs_iqama_alert


def test_days_until_expiry_can_be_negative_for_an_already_expired_iqama() -> None:
    assert days_until_expiry(date(2026, 1, 1), date(2026, 1, 10)) == -9


def test_needs_alert_false_when_comfortably_outside_the_window() -> None:
    assert needs_iqama_alert(date(2026, 12, 31), date(2026, 1, 1), threshold_days=90) is False


def test_needs_alert_true_at_exactly_the_threshold() -> None:
    assert needs_iqama_alert(date(2026, 4, 1), date(2026, 1, 1), threshold_days=90) is True


def test_needs_alert_true_when_already_expired() -> None:
    assert needs_iqama_alert(date(2026, 1, 1), date(2026, 6, 1), threshold_days=90) is True

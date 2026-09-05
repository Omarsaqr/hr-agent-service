from datetime import date

# A pragmatic ops threshold, not a legal one -- KSA Iqama renewal has no
# single mandated "start renewing by" day, but 90 days gives HR enough
# runway to act before it becomes urgent. Unlike the leave-entitlement
# tables, this isn't a citation the brief requires; it's a operational
# default, tunable per caller.
DEFAULT_ALERT_THRESHOLD_DAYS = 90


def days_until_expiry(expiry_date: date, as_of: date) -> int:
    return (expiry_date - as_of).days


def needs_iqama_alert(
    expiry_date: date, as_of: date, threshold_days: int = DEFAULT_ALERT_THRESHOLD_DAYS
) -> bool:
    """True once expiry is within threshold_days -- including an expiry
    already in the past (a negative days-remaining), which is more
    urgent than "soon," not exempt from it.
    """
    return days_until_expiry(expiry_date, as_of) <= threshold_days

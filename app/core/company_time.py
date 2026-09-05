from datetime import date, datetime
from zoneinfo import ZoneInfo

# The company's operating timezone -- used everywhere "today" needs to
# mean a specific business-calendar day, not whichever timezone a
# request happened to arrive in or a server happens to run in. A single
# shared definition matters here specifically: a write keyed by one
# timezone's "today" and a read keyed by another's can silently disagree
# for the few hours a day the two are on different calendar dates (this
# is exactly how a real check-in ended up reported as missing during
# this project's own end-to-end tests -- see docs/ROADMAP.md).
COMPANY_TIMEZONE = ZoneInfo("Asia/Riyadh")


def today_in_company_timezone(now: datetime) -> date:
    return now.astimezone(COMPANY_TIMEZONE).date()

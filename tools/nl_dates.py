"""nl_dates.py -- every listing date the sites render is a Newfoundland calendar day.

Fleet canonical (fleet/canonical/tools/nl_dates.py), byte-identical on Gander,
Avalon and Goose Bay. Mike (2026-09-28): "Sold dates a day early: it's a
timezone bug. site: render every date in America/St_Johns at the generator,
one shared helper".

The generators used to take CloseDate[:10]. That is right for NLAR Matrix's
naive local timestamps ("2026-09-25T00:00:00") but wrong for anything carrying
a UTC offset: a close at 23:30 NL is "2026-09-26T02:00:00Z", and [:10] made it
the 26th. nl_date() converts to America/St_Johns first, so the day is always
the NL day. The browser side (js/*.js) then formats that YYYY-MM-DD as a plain
calendar date (see turnerCalDate in js/sold-listings.js), never through
new Date("YYYY-MM-DD"), which is UTC midnight = the previous evening in NL.

    nl_date(v)        -> "YYYY-MM-DD" (the NL day) or "" when empty/unparseable
    nl_month_year(v)  -> "Sep 2026" or ""

Accepted inputs: date / datetime objects; "YYYY-MM-DD"; "YYYY-MM-DD[T ]HH:MM[:SS[.fff]]"
with an optional "Z" or "+hh:mm"/"-hhmm" offset. Naive timestamps are NL local
time (NLAR Matrix convention), so they keep their own date.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

NL_TZ = ZoneInfo("America/St_Johns")

_ISO = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?"
    r"\s*(Z|[+-]\d{2}:?\d{2})?$"
)


def _to_nl_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.date()
        return value.astimezone(NL_TZ).date()
    if isinstance(value, date):
        return value
    m = _ISO.match(str(value).strip())
    if not m:
        return None
    y, mo, d, hh, mi, ss, tz = m.groups()
    try:
        if hh is None:
            return date(int(y), int(mo), int(d))
        naive = datetime(int(y), int(mo), int(d), int(hh), int(mi), int(ss or 0))
    except ValueError:
        return None
    if tz is None:
        return naive.date()
    if tz == "Z":
        off = timezone.utc
    else:
        sign = -1 if tz[0] == "-" else 1
        digits = tz[1:].replace(":", "")
        off = timezone(sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:])))
    return naive.replace(tzinfo=off).astimezone(NL_TZ).date()


def nl_date(value) -> str:
    """The Newfoundland calendar day of `value` as "YYYY-MM-DD", or ""."""
    d = _to_nl_date(value)
    return d.isoformat() if d else ""


def nl_month_year(value) -> str:
    """The Newfoundland calendar month of `value` as "Sep 2026", or ""."""
    d = _to_nl_date(value)
    return d.strftime("%b %Y") if d else ""

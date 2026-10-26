#!/usr/bin/env python3
"""
Build an iCalendar (.ics) prayer-time calendar from the Islamic Centre
Edgware / Colindale timetable (WordPress "Daily Prayer Time" plugin).

Usage:
  python make_ics.py --csv timetable.csv -o prayer-times.ics
  python make_ics.py --url "https://islamiccentreedgware.org/wp-json/dpt/v1/prayertime?filter=download_timetable" -o prayer-times.ics
  Add --from 2026-10-26 to skip earlier days.

The timetable already gives local clock times (GMT in winter, BST in
summer), so every event is tagged TZID=Europe/London and any calendar app
shows the right time on both sides of the clock change.

Standard library only.
"""
import argparse
import csv
import io
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = "Europe/London"
SOURCE = "https://islamiccentrecolindale.org/ (timetable published at islamiccentreedgware.org)"
# Jumu'ah jamaat start times as listed on the Islamic Centre Edgware homepage.
# The mosque changes how many jamaats it holds through the year, so the list
# is kept per clock season; a list can have any number of times.
JUMUAH = {
    "GMT": ["12:30", "13:05", "13:30"],  # late October to late March
    "BST": ["12:30", "13:05", "13:30"],  # late March to late October
}
# One-off Fridays that differ from the season (e.g. Eid, or a mosque notice):
# "2026-12-25": ["13:00", "13:45"]. An empty list means no Jumu'ah events.
JUMUAH_DATES = {}
JUMUAH_MINUTES = 30  # khutbah + salah; cut short if the next jamaat starts sooner

VTIMEZONE = """BEGIN:VTIMEZONE
TZID:Europe/London
BEGIN:DAYLIGHT
TZOFFSETFROM:+0000
TZOFFSETTO:+0100
TZNAME:BST
DTSTART:19700329T010000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0100
TZOFFSETTO:+0000
TZNAME:GMT
DTSTART:19701025T020000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE"""


def hm(value):
    """'05:45:00' or '05:45' -> (5, 45); blank -> None."""
    value = (value or "").strip()
    if not value:
        return None
    parts = value.split(":")
    return int(parts[0]), int(parts[1])


def fmt(t):
    return f"{t[0]:02d}:{t[1]:02d}"


def dt(day, t):
    return datetime(day.year, day.month, day.day, t[0], t[1])


def ical_dt(d):
    return d.strftime("%Y%m%dT%H%M%S")


def jumuah_times(day):
    """Jumu'ah jamaat start times for a Friday, as sorted (h, m) tuples."""
    times = JUMUAH_DATES.get(day.isoformat())
    if times is None:
        noon = datetime(day.year, day.month, day.day, 12, tzinfo=ZoneInfo(TZ))
        times = JUMUAH["BST" if noon.dst() else "GMT"]
    return sorted(hm(t) for t in times)


def esc(text):
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line):
    """Fold lines longer than 75 octets per RFC 5545."""
    out, raw = [], line.encode("utf-8")
    while len(raw) > 75:
        cut = 75 if not out else 74
        while (raw[cut] & 0xC0) == 0x80:  # don't split a UTF-8 character
            cut -= 1
        out.append(raw[:cut].decode("utf-8"))
        raw = raw[cut:]
    out.append(raw.decode("utf-8"))
    return "\r\n ".join(out)


def event(uid, start, end, summary, description, stamp):
    return [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{stamp}",
        f"DTSTART;TZID={TZ}:{ical_dt(start)}",
        f"DTEND;TZID={TZ}:{ical_dt(end)}",
        f"SUMMARY:{esc(summary)}",
        f"DESCRIPTION:{esc(description)}",
        "TRANSP:TRANSPARENT",  # don't mark you as busy
        "END:VEVENT",
    ]


def jumuah_events(day, zuhr_begins, stamp):
    """One event per Jumu'ah jamaat, each blocking out its own slot."""
    # Jumu'ah can't be before Zuhr begins, so drop any jamaat the season's
    # list puts too early for this Friday.
    times = [t for t in jumuah_times(day) if not zuhr_begins or t >= zuhr_begins]
    listed = ", ".join(fmt(t) for t in times)
    events = []
    for i, t in enumerate(times):
        start = dt(day, t)
        end = start + timedelta(minutes=JUMUAH_MINUTES)
        if i + 1 < len(times):
            end = min(end, dt(day, times[i + 1]))
        title = "Jumu'ah" if len(times) == 1 else f"Jumu'ah {i + 1} of {len(times)}"
        desc = f"Jamaat {fmt(t)}"
        if zuhr_begins:
            desc += f" · Zuhr begins {fmt(zuhr_begins)}"
        desc += f"\nAll jamaats today: {listed} (check notices for changes)"
        desc += f"\nSource: {SOURCE}"
        events.append(event(f"{day.isoformat()}-jumuah-{i + 1}@colindale-prayer-times",
                            start, end, f"{title} · {fmt(t)}", desc, stamp))
    return events


def build(rows, start_from=None):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//prayer-times//Islamic Centre Colindale//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Prayer Times – Islamic Centre Colindale",
        f"X-WR-TIMEZONE:{TZ}",
        "REFRESH-INTERVAL;VALUE=DURATION:P1D",
        "X-PUBLISHED-TTL:P1D",
        VTIMEZONE,
    ]
    count = 0
    for r in rows:
        day = date.fromisoformat(r["d_date"].strip()[:10])
        if start_from and day < start_from:
            continue
        sunrise = hm(r.get("sunrise"))
        friday = day.weekday() == 4

        prayers = [
            ("Fajr", "fajr_begins", "fajr_jamah"),
            ("Zuhr", "zuhr_begins", "zuhr_jamah"),
            ("Asr", "asr_mithl_1", "asr_jamah"),
            ("Maghrib", "maghrib_begins", "maghrib_jamah"),
            ("Isha", "isha_begins", "isha_jamah"),
        ]
        for name, b_key, j_key in prayers:
            begins, jamaat = hm(r.get(b_key)), hm(r.get(j_key))
            if not begins and not jamaat:
                continue
            if name == "Zuhr" and friday:
                for ev in jumuah_events(day, begins, stamp):
                    lines += ev
                    count += 1
                continue
            # In midsummer the plugin stores Isha as 00:00 (no true darkness);
            # if "begins" is missing or after the jamaat, anchor on the jamaat.
            if begins and jamaat and dt(day, begins) > dt(day, jamaat):
                begins = None
            if begins is None or begins == (0, 0):
                start = dt(day, jamaat)
                end = start + timedelta(minutes=15)
                desc = f"Jamaat {fmt(jamaat)}"
            else:
                start = dt(day, begins)
                end = dt(day, jamaat) if jamaat else start + timedelta(minutes=15)
                if end <= start:
                    end = start + timedelta(minutes=5)
                desc = f"Begins {fmt(begins)}" + (f" · Jamaat {fmt(jamaat)}" if jamaat else "")
            title = name
            if jamaat:
                title += f" · jamaat {fmt(jamaat)}"
            if name == "Fajr" and sunrise:
                desc += f"\nSunrise {fmt(sunrise)} (Fajr ends)"
            if name == "Asr" and r.get("asr_mithl_2"):
                desc += f"\nAsr (Hanafi, 2nd mithl) begins {fmt(hm(r['asr_mithl_2']))}"
            desc += f"\nSource: {SOURCE}"
            lines += event(f"{day.isoformat()}-{name.lower()}@colindale-prayer-times",
                           start, end, title, desc, stamp)
            count += 1

        if sunrise:
            s = dt(day, sunrise)
            lines += event(f"{day.isoformat()}-sunrise@colindale-prayer-times",
                           s, s + timedelta(minutes=10), "Sunrise",
                           "End of Fajr time", stamp)
            count += 1

    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for block in lines for l in block.split("\n")) + "\r\n", count


def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", help="timetable CSV file")
    src.add_argument("--url", help="URL returning the timetable CSV")
    ap.add_argument("--from", dest="start_from", help="first date to include, YYYY-MM-DD")
    ap.add_argument("-o", "--out", default="prayer-times.ics")
    a = ap.parse_args()

    if a.url:
        req = urllib.request.Request(a.url, headers={"User-Agent": "prayer-times-ics/1.0"})
        text = urllib.request.urlopen(req, timeout=60).read().decode("utf-8-sig")
    else:
        with open(a.csv, encoding="utf-8-sig") as f:
            text = f.read()
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        sys.exit("No timetable rows found")
    rows.sort(key=lambda r: r["d_date"])

    start = date.fromisoformat(a.start_from) if a.start_from else None
    ics, n = build(rows, start)
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        f.write(ics)
    print(f"Wrote {n} events ({rows[0]['d_date'][:10]} to {rows[-1]['d_date'][:10]}) to {a.out}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Build an iCalendar (.ics) prayer-time calendar from the Islamic Centre
Edgware / Colindale timetable (WordPress "Daily Prayer Time" plugin).

Usage:
  python make_ics.py --csv timetable.csv -o prayer-times.ics
  python make_ics.py --url "https://islamiccentreedgware.org/wp-json/dpt/v1/prayertime?filter=download_timetable" -o prayer-times.ics
  Add --from 2026-10-26 to skip earlier days.

Jumu'ah times aren't in the timetable, so each run also reads them from the
mosque's homepage and saves them to data/jumuah.json. If the homepage can't
be read, the last saved times are used and a warning is raised.

The timetable already gives local clock times (GMT in winter, BST in
summer), so every event is tagged TZID=Europe/London and any calendar app
shows the right time on both sides of the clock change.

Standard library only.
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser

TZ = "Europe/London"
SOURCE = "https://islamiccentrecolindale.org/ (timetable published at islamiccentreedgware.org)"
# The homepage lists the Jumu'ah jamaats; however many it shows are used.
JUMUAH_URL = "https://islamiccentreedgware.org/"
JUMUAH_FILE = "data/jumuah.json"  # last times read, used if a read fails
UA = {"User-Agent": "prayer-times-ics/1.0"}

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


class PageText(HTMLParser):
    """Visible text of a page, one line per block element."""
    BLOCKS = {"br", "p", "div", "li", "tr", "td", "th", "h1", "h2", "h3", "h4",
              "h5", "h6", "section", "article", "table", "ul", "ol", "span"}

    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)

    def lines(self):
        text = "".join(self.parts).replace("\xa0", " ")
        return [" ".join(l.split()) for l in text.split("\n") if l.strip()]


JUM = re.compile(r"\bj[uo]m+[u']*['’`]?a?h?\b|\bjum[ua]", re.I)
OTHER_PRAYER = re.compile(r"\b(fajr|sunrise|shuruq|zuhr|dhuhr|zohr|asr|maghrib|isha)\b", re.I)
TIME = re.compile(r"\b(\d{1,2})[:.](\d{2})\s*([ap]\.?m\.?)?", re.I)


def parse_jumuah(html):
    """Jamaat times listed next to a Jumu'ah label, as sorted 'HH:MM' strings,
    plus the text they were read from."""
    p = PageText()
    p.feed(html)
    lines = p.lines()
    found, snippet = set(), []
    for i, line in enumerate(lines):
        m = JUM.search(line)
        if not m:
            continue
        # Read on from the label until another prayer's name comes up.
        window = [line[m.end():]] + lines[i + 1:i + 6]
        for j, text in enumerate(window):
            stop = OTHER_PRAYER.search(text)
            if stop:
                window[j] = text[:stop.start()]
                window = window[:j + 1]
                break
        for text in window:
            for h, mi, ampm in TIME.findall(text):
                h, mi = int(h), int(mi)
                if ampm.lower().startswith("p") and h < 12 or not ampm and h <= 6:
                    h += 12
                if 11 <= h <= 15 and mi < 60:  # Jumu'ah is always around midday
                    found.add(f"{h:02d}:{mi:02d}")
                    snippet.append(text.strip())
    return sorted(found), " | ".join(dict.fromkeys(snippet))


def warn(msg):
    """Note a problem in the log and, under GitHub Actions, on the run page."""
    print(f"WARNING: {msg}", file=sys.stderr)
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::warning title=Jumu'ah times::{msg}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"⚠️ {msg}\n\n")


def load_jumuah(url, path):
    """Read the Jumu'ah times from the homepage and save them; if that fails,
    fall back to the last saved times. Returns sorted (h, m) tuples."""
    saved = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        req = urllib.request.Request(url, headers=UA)
        html = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
        times, snippet = parse_jumuah(html)
        if not times:
            raise ValueError("no Jumu'ah times found on the page")
        print(f"Jumu'ah times read from {url}: {', '.join(times)} (from: {snippet[:300]})")
        saved = {"times": times, "read_at": now, "source": url}
    except Exception as e:
        if not saved.get("times"):
            sys.exit(f"Couldn't read Jumu'ah times from {url} ({e}) and none are saved in {path}")
        warn(f"Couldn't read Jumu'ah times from {url} ({e}); using the times saved "
             f"on {saved['read_at'][:10]}: {', '.join(saved['times'])}")
        saved.update(last_error=str(e), last_error_at=now)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(saved, f, indent=2)
        f.write("\n")
    return sorted({hm(t) for t in saved["times"]})


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


def jumuah_events(day, zuhr_begins, jumuah, stamp):
    """One event per Jumu'ah jamaat, laid out like the other prayers: Zuhr
    begins -> 1st jamaat, then 1st -> 2nd jamaat, and so on."""
    # Jumu'ah can't be before Zuhr begins, so drop any jamaat listed too early
    # for this Friday.
    times = [t for t in jumuah if not zuhr_begins or t >= zuhr_begins]
    listed = ", ".join(fmt(t) for t in times)
    events = []
    prev = zuhr_begins
    for i, t in enumerate(times):
        end = dt(day, t)
        if prev is None:
            start = end
            end = start + timedelta(minutes=15)
        else:
            start = dt(day, prev)
            if end <= start:
                end = start + timedelta(minutes=5)
        title = "Jumu'ah" if len(times) == 1 else f"Jumu'ah {i + 1} of {len(times)}"
        desc = f"Jamaat {fmt(t)}"
        if zuhr_begins:
            desc += f" · Zuhr begins {fmt(zuhr_begins)}"
        desc += f"\nAll jamaats today: {listed} (check notices for changes)"
        desc += f"\nSource: {SOURCE}"
        events.append(event(f"{day.isoformat()}-jumuah-{i + 1}@colindale-prayer-times",
                            start, end, f"{title} · jamaat {fmt(t)}", desc, stamp))
        prev = t
    return events


def build(rows, jumuah, start_from=None):
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
                for ev in jumuah_events(day, begins, jumuah, stamp):
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
    ap.add_argument("--jumuah-url", default=JUMUAH_URL, help="page listing the Jumu'ah times")
    ap.add_argument("--jumuah-file", default=JUMUAH_FILE, help="where the last Jumu'ah times are saved")
    ap.add_argument("-o", "--out", default="prayer-times.ics")
    a = ap.parse_args()

    if a.url:
        req = urllib.request.Request(a.url, headers=UA)
        text = urllib.request.urlopen(req, timeout=60).read().decode("utf-8-sig")
    else:
        with open(a.csv, encoding="utf-8-sig") as f:
            text = f.read()
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        sys.exit("No timetable rows found")
    rows.sort(key=lambda r: r["d_date"])

    start = date.fromisoformat(a.start_from) if a.start_from else None
    jumuah = load_jumuah(a.jumuah_url, a.jumuah_file)
    ics, n = build(rows, jumuah, start)
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        f.write(ics)
    print(f"Wrote {n} events ({rows[0]['d_date'][:10]} to {rows[-1]['d_date'][:10]}) to {a.out}")


if __name__ == "__main__":
    main()

# Prayer Times – Islamic Centre Colindale

An auto-updating calendar of daily prayer times for Islamic Centre Colindale
that works in any calendar app: Apple Calendar (iPhone, iPad, Mac), Google
Calendar (and Android), Outlook, Proton Calendar, Thunderbird and anything
else that can subscribe to an iCalendar (`.ics`) link.

**Subscribe page:** https://zain506.github.io/prayer-times-calendar/
(one-tap buttons plus instructions for each app)

**Calendar link:** `https://zain506.github.io/prayer-times-calendar/prayer-times.ics`

## What's in it

- Each prayer is one event from **start time → jamaat time**, e.g.
  `Fajr · jamaat 05:45` from 04:51 to 05:45.
- Sunrise is a short marker event.
- On Fridays, Zuhr is replaced by one event per Jumu'ah jamaat (e.g.
  `Jumu'ah 1 of 3 · 12:30` from 12:30 to 13:00), so each jamaat fills its own
  slot in your calendar.
- Events are marked "free", so they never block your availability.
- Times are tagged `Europe/London`, so GMT/BST is handled by your calendar app
  automatically.

## How to subscribe

| App | How |
| --- | --- |
| iPhone / iPad | Open the subscribe page and tap **Apple Calendar**, or Settings → Calendar → Accounts → Add Account → Other → Add Subscribed Calendar |
| Mac | Tap **Apple Calendar** on the subscribe page, or Calendar → File → New Calendar Subscription |
| Google Calendar | calendar.google.com → **+** next to Other calendars → **From URL** (Android picks it up from there; turn on Sync for it in the app if it doesn't appear) |
| Outlook (web / new) | Calendar → Add calendar → **Subscribe from web** |
| Outlook (classic Windows) | Home → Add Calendar → **From Internet** |
| Proton Calendar | **+** next to My calendars → **Add calendar from URL** |

Each app refreshes subscriptions on its own schedule; Google can take up to a
day to show changes.

## How it works

- `make_ics.py` downloads the mosque's timetable (islamiccentrecolindale.org
  points to the Islamic Centre Edgware site, which publishes it through the
  "Daily Prayer Time" WordPress plugin) and turns it into a standard
  iCalendar file. Standard library Python only.
- `.github/workflows/build-calendar.yml` runs it every Monday (or by hand from
  the **Actions** tab) and commits `docs/prayer-times.ics`.
- GitHub Pages serves the `docs/` folder, giving the public link above.

The feed keeps a week of history plus everything ahead, to stay small.

Run it locally:

```
python make_ics.py --url "https://islamiccentreedgware.org/wp-json/dpt/v1/prayertime?filter=download_timetable" -o prayer-times.ics
```

## Things to know

- The mosque's API only serves its latest uploaded year. Once they publish
  next year's timetable the feed picks it up automatically; until then the
  feed ends on 31 December.
- Asr uses the first-mithl time (as shown on the site); the Hanafi time is in
  each Asr event's notes.
- In midsummer the timetable lists Isha as 00:00 (no full darkness), so those
  days' Isha event is placed at the jamaat time instead.
- The Jumu'ah times are the ones on the Edgware homepage. They live in
  `JUMUAH` in `make_ics.py`, with a separate list for GMT and BST so the
  number of jamaats can change with the season; `JUMUAH_DATES` overrides a
  single Friday (Eid, a notice from the mosque). Each block lasts
  `JUMUAH_MINUTES` (30), cut short if the next jamaat starts sooner, and any
  jamaat listed before Zuhr begins that day is left out.
- Not an official mosque service; follow the mosque's notices if anything differs.

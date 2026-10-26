# Prayer Times – Islamic Centre Colindale (auto-updating calendar)

Builds a subscribable `.ics` calendar from the mosque's published timetable
(islamiccentrecolindale.org points to the Islamic Centre Edgware site, which
publishes the timetable through its "Daily Prayer Time" plugin).

Each prayer is one event running from **start time → jamaat time**, e.g.
`Fajr · jamaat 05:45` from 04:51 to 05:45. Sunrise is a short marker event.
Fridays show `Jumu'ah` with the jamaat times. Events are "free" so they never
block your availability.

Times are tagged `Europe/London`, so GMT/BST is handled automatically.

## One-off import (no setup)

Proton Calendar → Settings → Calendars → Import → choose
`prayer-times-colindale-2026.ics`. Import it into a new calendar called
e.g. "Prayer Times" so you can hide or delete it in one go later.

## Auto-updating subscription link (GitHub, free)

1. Create a **public** GitHub repo (e.g. `prayer-times-calendar`) and upload
   `make_ics.py` and `.github/workflows/build-calendar.yml`
   (keep the folder path exactly).
2. Repo → **Actions** tab → enable workflows → open "Build prayer-time
   calendar" → **Run workflow**. It creates `docs/prayer-times.ics`.
3. Repo → **Settings → Pages** → Source: "Deploy from a branch",
   branch `main`, folder `/docs` → Save.
4. Your feed URL is
   `https://zain506.github.io/prayer-times-calendar/prayer-times.ics`
5. Proton Calendar → **+** next to My Calendars → **Add calendar from URL**
   → paste the link.

The workflow refreshes the file every Monday; Proton re-syncs subscribed
calendars every few hours. The feed keeps a week of history plus everything
ahead, to stay small.

## Things to know

- The mosque's API only serves its latest uploaded year. Once they publish
  next year's timetable the feed picks it up automatically; until then the
  feed ends on 31 December.
- Asr uses the first-mithl time (as shown on the site); the Hanafi time is in
  each Asr event's notes.
- In midsummer the timetable lists Isha as 00:00 (no full darkness), so those
  days' Isha event is placed at the jamaat time instead.
- The Jumu'ah times are the ones on the Edgware homepage — edit `JUMUAH` in
  `make_ics.py` if Colindale's differ.

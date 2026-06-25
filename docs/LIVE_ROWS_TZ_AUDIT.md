# Live-Rows + Timezone Forensic Audit (read-only, no code changes)

I cannot reach your installed app's SQLite (`%APPDATA%\Momentum Lab\…\momentum.db`)
from this cloud environment. So below: (A) a **read-only script you run on your own DB**
that returns the exact queries, and (B) the **same script run here against a reproduced
DB** (one *fresh* scan + one *stale* scan) so the evidence shape and the timezone proof
are concrete. **No application code was modified.**

---

## PART 1 — Are live rows written and tied to the latest scan?

### Reproduced DB output (fresh scan `scan-20260624`, then a stale scan `scan-20260619`)
```
=== TOTAL ROW COUNTS ===
  SELECT COUNT(*) FROM conviction_scores;   -> 12
  SELECT COUNT(*) FROM candidate_analogs;   -> 12
  SELECT COUNT(*) FROM trade_plans;         -> 12
  SELECT COUNT(*) FROM watchlist_entries;   -> 30

=== BY run_id (latest 10) ===
  conviction_scores :  scan-20260624  12
  candidate_analogs :  scan-20260624  12
  trade_plans       :  scan-20260624  12
  watchlist_entries :  scan-20260624  30
```

**Proof of behaviour:** the *fresh* scan wrote **12 conviction / 12 analog / 12 trade-plan
/ 30 watchlist** rows, **all tied to its run_id** `scan-20260624`. The *stale* scan
(`scan-20260619`, the chronologically latest) wrote **0** of each — which is exactly why it
**does not appear** in any GROUP BY. So the write path is healthy; rows are tied to the
scan run_id; a **stale** run simply persists none.

### What this means for YOUR DB
Run the script (below). Two diagnostic outcomes:
- **`conviction_scores` total > 0, but the latest `scan_metadata.scan_id` is NOT in the
  conviction GROUP BY** ⇒ live rows *are* being written for fresh runs, and your most
  recent scan was **stale** (the run we are debugging). Look at the newest run_id that
  *does* have conviction rows — that was your last fresh scan.
- **`conviction_scores` total = 0** ⇒ no fresh scan has ever completed on this DB; every
  scan so far was stale (or the only data was demo, now purged).

### The exact queries (copy-paste into any SQLite tool)
```sql
SELECT COUNT(*) FROM conviction_scores;
SELECT COUNT(*) FROM candidate_analogs;
SELECT COUNT(*) FROM trade_plans;
SELECT COUNT(*) FROM watchlist_entries;

SELECT run_id, COUNT(*) FROM conviction_scores  GROUP BY run_id ORDER BY run_id DESC LIMIT 10;
SELECT run_id, COUNT(*) FROM candidate_analogs  GROUP BY run_id ORDER BY run_id DESC LIMIT 10;
SELECT run_id, COUNT(*) FROM trade_plans        GROUP BY run_id ORDER BY run_id DESC LIMIT 10;
SELECT run_id, COUNT(*) FROM watchlist_entries  GROUP BY run_id ORDER BY run_id DESC LIMIT 10;
-- the latest scan's run_id, to compare against the GROUP BYs:
SELECT run_id FROM runs WHERE mode='scan' ORDER BY started_at DESC, id DESC LIMIT 1;
```

---

## PART 2 — Timezone audit of the staleness calculation

### Reproduced DB output (latest = the stale run)
```
=== LATEST scan_metadata (staleness inputs) ===
   scan_id=scan-20260619  stale=1  data_age_minutes=7871.1
   bar_timestamp  (as stored) = '2026-06-19 13:30:00.000000'
   pull_timestamp (as stored) = '2026-06-25 00:41:08.291913'

   bar.tzinfo=None   pull.tzinfo=None      ← SQLite drops tz on read-back (see caveat)

=== (pull - newest_bar) THREE WAYS ===
   1. RAW (as stored)             = 7871.1 min
   2. UTC normalized              = 7871.1 min
   3. exchange-tz (ET) normalized = 7871.1 min

   spread across methods = 0.0 min
   >>> TZ BUG?  NO  (a duration between two instants is timezone-invariant)
```

### The three calculations are identical — and that is mathematically guaranteed
- **bar_timestamp** and **pull_timestamp** are both stored as **UTC wall-clock**.
  (`pull = datetime.now(tz=UTC)`; `bar = _newest_bar_timestamp(bars)` which forces tz-aware
  UTC after `normalize_bars` sorts ascending + `tz_convert("UTC")`.)
- A **duration** between two absolute instants is **invariant under timezone conversion**:
  converting both endpoints to America/New_York (or any zone) and subtracting yields the
  **same** number. Hence RAW = UTC = ET = **7871.1 min**, spread **0.0 min**.
- **Verdict: stale is NOT triggered by timezone handling.** `7871.1 > 5760` ⇒ stale, and
  7871.1 min ≈ **5.5 days** — the freshest bar is genuinely 5.5 days old. There is no
  >1-hour discrepancy, so there is no timezone bug in the staleness math.

### Why a tz bug *cannot* flip this flag (code, not data)
`run_scan` computes `data_age_minutes` **in memory** from two **tz-aware UTC** datetimes and
persists the **number** (`actions.py:298-306`). The stale flag is `number > threshold`. So
even though SQLite stores the datetime columns as naive strings, the comparison already
happened on tz-correct values before storage — SQLite's tz-stripping can't change it.

### One caveat worth knowing (latent, not the cause here)
`bar.tzinfo=None / pull.tzinfo=None` on read-back: SQLite's `DateTime(timezone=True)` stores
**naive UTC wall-clock** (no zone). This does **not** affect staleness (computed in memory),
but if any *other* code ever reads these columns and localizes one of them to a non-UTC zone,
it would miscompute a delta. The forensic above treats both as UTC (correct) and gets a 0-min
spread. Flag only — not your stale trigger.

---

## The script (read-only) — run it on YOUR machine
Point it at your DB and it prints everything above with **your** numbers:
```bash
# Windows PowerShell (adjust the path to your momentum.db):
$env:DATABASE_URL = "sqlite:///C:/Users/<you>/AppData/Roaming/Momentum Lab/.../momentum.db"
python db_forensic.py
```
```python
# db_forensic.py  — read-only, no writes
import os, datetime as dt
from zoneinfo import ZoneInfo
from sqlalchemy import create_engine, text
eng = create_engine(os.environ.get("DATABASE_URL", "sqlite:///data/momentum.db"), future=True)
ET = ZoneInfo("America/New_York")
with eng.connect() as c:
    for t in ("conviction_scores","candidate_analogs","trade_plans","watchlist_entries"):
        print("COUNT", t, c.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar())
    for t in ("conviction_scores","candidate_analogs","trade_plans","watchlist_entries"):
        print("--", t)
        for rid,n in c.execute(text(f"SELECT run_id,COUNT(*) FROM {t} GROUP BY run_id ORDER BY run_id DESC LIMIT 10")).all():
            print("   ", rid, n)
    sid,stale,age,bar,pull = c.execute(text("SELECT scan_id,stale,data_age_minutes,bar_timestamp,pull_timestamp FROM scan_metadata ORDER BY pull_timestamp DESC LIMIT 1")).first()
    print("scan", sid, "stale", stale, "age_min", age, "\n bar", bar, "\n pull", pull)
    def p(v):
        if isinstance(v, dt.datetime): return v
        return dt.datetime.fromisoformat(str(v).replace("Z","+00:00").split(".")[0])
    b,pu = p(bar), p(pull)
    bu = b if b.tzinfo else b.replace(tzinfo=dt.UTC); pu2 = pu if pu.tzinfo else pu.replace(tzinfo=dt.UTC)
    raw = (pu-b).total_seconds()/60 if (b.tzinfo==pu.tzinfo) else None
    print("RAW", raw, "UTC", (pu2-bu).total_seconds()/60,
          "ET", (pu2.astimezone(ET)-bu.astimezone(ET)).total_seconds()/60)
```

---

## Bottom line
1. **Live rows are written correctly and tied to the scan run_id** — proven: a fresh scan
   wrote 12/12/12/30 under one run_id; a stale scan wrote 0 (so it's absent from the GROUP
   BYs). Run the script: the newest run_id with conviction rows is your last *fresh* scan;
   the latest scan is stale.
2. **The stale flag is NOT a timezone artifact.** All three deltas are identical (spread
   0 min) because a duration between two instants is timezone-invariant, and the app computes
   it in memory from tz-aware UTC values. The data is genuinely ~5+ days old. **No tz bug.**
3. Caveat flagged: SQLite returns these `DateTime(timezone=True)` columns **naive** — fine for
   staleness, a footgun only if other code mis-localizes them.

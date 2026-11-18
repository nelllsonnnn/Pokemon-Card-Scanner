#!/usr/bin/env python3
"""Pokemon singles price-movement tracker.

Pulls TCGplayer market prices (via tcgcsv.com's daily mirror of TCGplayer
data), compares the latest snapshot against 1, 7 and 30 days earlier, and
flags singles whose market price spiked or dropped sharply.

Usage:  python3 tracker.py [--out DIR] [--day-pct 15] [--week-pct 25] ...
Needs:  pip install py7zr
"""
import argparse, datetime as dt, io, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
import urllib.request

import py7zr

BASE = "https://tcgcsv.com"
CAT = 3  # Pokemon (English)
CATS = {3: "en", 85: "jp"}  # TCGplayer categories: Pokemon, Pokemon Japan
UA = {"User-Agent": "pokeprice-tracker/1.0"}


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(2 ** i)


def load_snapshot(day, cache):
    """Return {(productId, subType): (market, low, mid)} for a date (English and Japanese cards), or None if no archive."""
    path = os.path.join(cache, f"prices4-{day}.json")
    if os.path.exists(path):
        return {tuple(json.loads(k)): tuple(v) for k, v in json.load(open(path)).items()}
    try:
        raw = get(f"{BASE}/archive/tcgplayer/prices-{day}.ppmd.7z", tries=2)
    except Exception:  # noqa: BLE001
        return None
    out = {}
    with py7zr.SevenZipFile(io.BytesIO(raw)) as z:
        names = [n for n in z.getnames() if any(f"/{c}/" in n for c in CATS) and n.endswith("/prices")]
        z.extract(path=os.path.join(cache, "x"), targets=names)
    root = os.path.join(cache, "x")
    for n in names:
        for p in json.load(open(os.path.join(root, n)))["results"]:
            if p.get("marketPrice"):
                out[(p["productId"], p["subTypeName"])] = (p["marketPrice"], p.get("lowPrice"), p.get("midPrice"))
    json.dump({json.dumps(list(k)): v for k, v in out.items()}, open(path, "w"))
    return out


def find_snapshot(target, cache, back=4):
    """Archive for `target`, or the closest earlier day that exists."""
    for i in range(back):
        d = target - dt.timedelta(days=i)
        s = load_snapshot(d.isoformat(), cache)
        if s:
            return d, s
    return None, None


def load_catalog(cache):
    """Singles only, English and Japanese: {productId: {...card info, lang...}}. Cached for 1 day."""
    path = os.path.join(cache, "catalog2.json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < 86400:
        return {int(k): v for k, v in json.load(open(path)).items()}
    groups = [(cat, g) for cat in CATS for g in json.loads(get(f"{BASE}/tcgplayer/{cat}/groups"))["results"]]

    def fetch(cg):
        cat, g = cg
        prods = json.loads(get(f"{BASE}/tcgplayer/{cat}/{g['groupId']}/products"))["results"]
        rows = {}
        for p in prods:
            ext = {e["name"]: e["value"] for e in p.get("extendedData", [])}
            if "Number" not in ext:  # sealed product, code card, etc.
                continue
            rows[p["productId"]] = {
                "name": p["name"], "set": g["name"], "number": ext["Number"],
                "rarity": ext.get("Rarity", ""), "url": p["url"], "img": p["imageUrl"], "lang": CATS[cat],
            }
        return rows

    cat = {}
    with ThreadPoolExecutor(8) as ex:
        for rows in ex.map(fetch, groups):
            cat.update(rows)
    json.dump(cat, open(path, "w"))
    return cat


def pct(new, old):
    return None if not old else round((new - old) / old * 100, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--cache", default=os.path.expanduser("~/.cache/pokeprice"))
    ap.add_argument("--day-pct", type=float, default=15, help="alert if 1-day move >= this %%")
    ap.add_argument("--week-pct", type=float, default=25, help="alert if 7-day move >= this %%")
    ap.add_argument("--min-price", type=float, default=3, help="ignore cards cheaper than this (both before and after)")
    ap.add_argument("--min-change", type=float, default=1.5, help="ignore moves smaller than this many dollars")
    a = ap.parse_args()
    os.makedirs(a.cache, exist_ok=True)

    today = dt.datetime.now(dt.timezone.utc).date()
    d0, now = find_snapshot(today, a.cache)
    if not now:
        sys.exit("No recent price snapshot available")
    d1, prev = find_snapshot(d0 - dt.timedelta(days=1), a.cache)
    d7, week = find_snapshot(d0 - dt.timedelta(days=7), a.cache)
    d30, month = find_snapshot(d0 - dt.timedelta(days=30), a.cache)
    # Each of the last 8 days, to count how often a card's market price moved (it moves only when the card sells).
    daily = [now] + [load_snapshot((d0 - dt.timedelta(days=i)).isoformat(), a.cache) for i in range(1, 8)]
    cat = load_catalog(a.cache)

    cards, alerts, jp_cards = [], [], []
    thin = 0
    def mk(snap, key):
        v = snap.get(key) if snap else None
        return v[0] if v else None

    for (pid, sub), (price, low, mid) in now.items():
        info = cat.get(pid)
        if not info:
            continue
        k = (pid, sub)
        p1, p7, p30 = mk(prev, k), mk(week, k), mk(month, k)
        seen = [s_.get(k) for s_ in daily if s_]
        chg7 = sum(1 for x, y in zip(seen, seen[1:]) if x and y and x[0] != y[0])
        row = {**info, "id": pid, "variant": sub, "price": price, "low": low, "mid": mid, "chg7": chg7,
               "p1": p1, "p7": p7, "p30": p30,
               "c1": pct(price, p1), "c7": pct(price, p7), "c30": pct(price, p30)}
        if info.get("lang") != "en":  # Japanese: priced for the scanner only, not in the movers dashboard
            jp_cards.append(row)
            continue
        cards.append(row)
        reasons = []
        for base, ch, lim, label in ((p1, row["c1"], a.day_pct, "1d"), (p7, row["c7"], a.week_pct, "7d")):
            if ch is None or abs(ch) < lim:
                continue
            if max(price, base) < a.min_price or min(price, base) < a.min_price / 3:
                continue
            if abs(price - base) < a.min_change:
                continue
            # Confirm with live listings: a real spike lifts the cheapest listing too,
            # a real drop pulls it down. Otherwise it's likely one odd sale.
            if low is None or not (price / 2 <= low <= price * 2):
                thin += 1
                continue
            if ch > 0 and low < base * (1 + lim / 200):
                thin += 1
                continue
            if ch < 0 and low > base * (1 - lim / 200):
                thin += 1
                continue
            reasons.append(label)
        if reasons:
            row["why"] = reasons
            alerts.append(row)

    def strength(r):
        return max(abs(r["c1"] or 0) if "1d" in r["why"] else 0, abs(r["c7"] or 0) if "7d" in r["why"] else 0)
    alerts.sort(key=strength, reverse=True)

    def top(key, rev, n=25):
        pool = [c for c in cards if c[key] is not None and c["price"] >= a.min_price]
        return sorted(pool, key=lambda c: c[key], reverse=rev)[:n]

    result = {
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "dates": {"now": str(d0), "d1": str(d1), "d7": str(d7), "d30": str(d30) if d30 else None},
        "thresholds": vars(a) | {"out": None, "cache": None},
        "tracked": len(cards), "filtered_thin": thin,
        "spikes": [r for r in alerts if strength_dir(r) > 0],
        "drops": [r for r in alerts if strength_dir(r) < 0],
        "gainers7": top("c7", True), "losers7": top("c7", False),
        "expensive": sorted(cards, key=lambda c: c["price"], reverse=True)[:50],
    }
    write_dashboard_files(result, a, thin)
    write_price_file(cards, result["dates"], a.out)
    write_price_file(jp_cards, result["dates"], a.out, "prices_jp.json")

    s, d = result["spikes"], result["drops"]
    print(f"Prices as of {d0} | {len(cards):,} English singles tracked ({len(jp_cards):,} Japanese priced for the scanner) | {len(s)} spikes, {len(d)} drops"
          f" ({thin} unconfirmed moves ignored)")
    for title, rows in (("SPIKES", s), ("DROPS", d)):
        if rows:
            print(f"\n{title}")
        for r in rows[:15]:
            print(f"  {r['name']} ({r['set']} {r['number']}, {r['variant']}): ${r['price']:,.2f}"
                  f"  1d {fmt(r['c1'])} (was ${r['p1'] or 0:,.2f})  7d {fmt(r['c7'])} (was ${r['p7'] or 0:,.2f})"
                  f"  lowest listing ${r['low']:,.2f}")


FIELDS = ("name", "set", "number", "rarity", "variant", "price", "low",
          "p1", "c1", "p7", "c7", "p30", "c30", "url")


def write_dashboard_files(result, a, thin):
    """movers.json (one row per flagged card) and summary.json for the dashboard."""
    rows = []
    for lst, src in (("spike", result["spikes"]), ("drop", result["drops"]),
                     ("gainer7", result["gainers7"]), ("loser7", result["losers7"])):
        for rank, r in enumerate(src, 1):
            rows.append({"key": f"{lst}:{r['id']}:{r['variant']}", "list": lst, "rank": rank,
                         "trigger": "+".join(r.get("why", [])) or None,
                         **{f: r.get(f) for f in FIELDS}})
    code = open(os.path.abspath(__file__)).read()
    meta = [{"label": "tracker.py", "value": code, "type": "code", "lang": "python"},
            {"label": "Input", "value": "TCGplayer market prices, daily archives from tcgcsv.com"}]
    d = result["dates"]
    summary = [{"asof": d["now"], "compared_1d": d["d1"], "compared_7d": d["d7"],
                "tracked": result["tracked"], "spikes": len(result["spikes"]),
                "drops": len(result["drops"]), "unconfirmed": thin,
                "day_pct": a.day_pct, "week_pct": a.week_pct, "min_price": a.min_price,
                "min_change": a.min_change, "generated": result["generated"]}]
    os.makedirs(os.path.join(a.out, "dashboard"), exist_ok=True)
    json.dump({"rows": rows, "meta": meta}, open(os.path.join(a.out, "dashboard", "movers.json"), "w"))
    json.dump({"rows": summary, "meta": meta[1:]}, open(os.path.join(a.out, "dashboard", "summary.json"), "w"))


def write_price_file(cards, dates, out, name="prices.json"):
    """scanner/prices.json: every single's current, 1/7/30-day-ago price, mid listing price and
    number of days in the last week its market price changed (a sales-activity signal), for the card scanner."""
    sets, idx, rows = [], {}, []
    for c in cards:
        if c["set"] not in idx:
            idx[c["set"]] = len(sets)
            sets.append(c["set"])
        rows.append([c["id"], c["name"], idx[c["set"]], c["number"], c["rarity"], c["variant"],
                     c["price"], c["low"], c["p1"], c["p7"], c["p30"], c["mid"], c["chg7"]])
    os.makedirs(os.path.join(out, "scanner"), exist_ok=True)
    json.dump({"asof": dates["now"], "d7": dates["d7"], "d30": dates["d30"], "sets": sets,
               "cols": ["id", "name", "set", "number", "rarity", "variant", "price", "low", "p1", "p7", "p30", "mid", "chg7"],
               "rows": rows}, open(os.path.join(out, "scanner", name), "w"), separators=(",", ":"))


def strength_dir(r):
    c = r["c1"] if "1d" in r["why"] else r["c7"]
    return c or 0


def fmt(c):
    return "  n/a" if c is None else f"{c:+.1f}%"


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Weekly sticker-price report for the Vending inventory.

Same rules as the scanner page: the sticker price is the TCGplayer market price
(for every condition).  Each card also gets a demand rating from a 0-100 score:
60% sales activity (days of the last 7 the market price moved) + 25% how close
the cheapest listing is to market + 15% how close the mid listing price is to
market.  60+ = high, 30-59 = medium, below 30 = low.  A card needs a new sticker
when the price on its sticker (tag) is off by 5% or more (at least $0.50).

Usage:  python3 sticker_report.py INV_DIR PRICES_JSON [MORE_PRICES_JSON ...]
  INV_DIR      one JSON file per inventory document (ArtifactData list out_dir of
               data/users/me/vend/inv)
  PRICES_JSON  the scanner's prices.json (and prices_jp.json for Japanese cards)
Prints a plain-text report.
"""
import glob, json, math, os, re, sys


def nice_round(x):
    step = 0.25 if x < 10 else 0.5 if x < 50 else 1 if x < 500 else 5
    return math.floor(x / step + 0.5) * step


def demand(v):
    if not v or not (v.get("price") or 0) > 0 or v.get("chg7") is None:
        return None
    p, low, mid = v["price"], v.get("low"), v.get("mid")
    act = v["chg7"] / 7
    sp = max(0, 1 - abs(p - low) / p / 0.3) if low and low > 0 else 0
    mc = max(0, 1 - abs(mid - p) / p / 0.5) if mid and mid > 0 else 0
    score = round(100 * (0.6 * act + 0.25 * sp + 0.15 * mc))
    level = "high" if score >= 60 else "medium" if score >= 30 else "low"
    mult = min(1.10, 1.05 + 0.05 * (score - 60) / 40) if score >= 60 else 1 + 0.04 * score / 59
    return {"score": score, "level": level, "mult": mult}


CONDS = {"NM": ("Near Mint", 1.0), "LP": ("Lightly Played", 1.0), "MP": ("Moderately Played", 1.0),
         "HP": ("Heavily Played", 1.0), "DMG": ("Damaged", 1.0)}


def cond_key(text):
    s = re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()
    if not s:
        return "NM"
    if s in ("nm", "lp", "mp", "hp", "dmg"):
        return s.upper()
    if re.search(r"\b(dmg|damaged|poor)\b", s):
        return "DMG"
    if re.search(r"\b(hp|heavily)\b", s):
        return "HP"
    if re.search(r"\b(mp|moderately)\b", s):
        return "MP"
    if re.search(r"\b(lp|lightly|excellent)\b", s):
        return "LP"
    if re.search(r"\bplayed\b", s):
        return "MP"
    return "NM"


def money(x):
    return "—" if x is None else f"${x:,.2f}"


def main(inv_dir, *prices_paths):
    live, d = {}, None
    for path in prices_paths:
        pf = json.load(open(path))
        d = d or pf
        C = {c: i for i, c in enumerate(pf["cols"])}
        for r in pf["rows"]:
            live[(r[C["id"]], r[C["variant"]])] = {k: (r[C[k]] if k in C else None)
                                                   for k in ("price", "low", "mid", "chg7", "p7")}
    restick, own, moves = [], [], []
    n_cards = 0
    value = 0.0
    for path in sorted(glob.glob(os.path.join(inv_dir, "*.json"))):
        it = json.load(open(path))
        qty = int(it.get("qty") or 0)
        if qty <= 0:
            continue
        n_cards += qty
        v = live.get((it.get("cardId"), it.get("variant"))) if it.get("cardId") is not None else None
        dm = demand(v)
        ck = cond_key(it.get("cond"))
        nm = v["price"] if v and v.get("price") else (it.get("market") or None)
        market = round(nm * CONDS[ck][1], 2) if nm else None
        auto = market
        custom = it.get("custom") if (it.get("custom") or 0) > 0 else None
        sticker = custom or auto
        tag = it.get("tag") if (it.get("tag") or 0) > 0 else None
        value += (sticker or 0) * qty
        lang = "JP" if re.match(r"(ja|jp|japanese)", str(it.get("lang") or ""), re.I) else ""
        label = " · ".join(x for x in (it.get("name"), it.get("set"), it.get("number"), it.get("variant"), lang, ck) if x)
        dl = f"{dm['level']} demand" if dm else "demand unknown"
        if tag and sticker and abs(sticker - tag) >= max(0.5, tag * 0.05):
            restick.append((abs(sticker - tag) * qty, f"{label} (×{qty}): {money(tag)} → {money(sticker)}"
                            f" ({'+' if sticker > tag else '−'}{abs(sticker - tag) / tag * 100:.0f}%, {dl}, market {money(market)})"))
        if custom and auto and abs(custom - auto) >= max(0.5, custom * 0.05):
            own.append(f"{label}: your price {money(custom)}, suggested {money(auto)} ({dl}, market {money(market)})")
        if v and v.get("p7") and v.get("price"):
            ch = (v["price"] - v["p7"]) / v["p7"] * 100
            if abs(ch) >= 10 and abs(v["price"] - v["p7"]) >= 1:
                moves.append((abs(ch), f"{label}: {money(v['p7'])} → {money(v['price'])} ({ch:+.0f}% this week)"))

    restick.sort(reverse=True)
    moves.sort(reverse=True)
    out = [f"Sticker update (prices as of {d.get('asof')}): {len(restick)} to re-sticker"
           f" · {n_cards} cards in inventory · sticker value {money(value)}"]
    if restick:
        out.append("\nRe-sticker these:")
        out += [f"- {s}" for _, s in restick]
    else:
        out.append("\nAll stickers are within 5% of today's suggested price. Nothing to re-sticker.")
    if own:
        out.append("\nYour own prices that are now off from the suggested price:")
        out += [f"- {s}" for s in own]
    if moves:
        out.append("\nBiggest market moves in your inventory this week:")
        out += [f"- {s}" for _, s in moves[:10]]
    print("\n".join(out))


if __name__ == "__main__":
    main(sys.argv[1], *sys.argv[2:])

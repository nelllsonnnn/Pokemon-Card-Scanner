# Pokémon Card Scanner

Tracks TCGplayer market prices for every English Pokémon single, flags sharp
spikes and drops, and powers a phone-friendly scanner that tells you whether a
card's asking price is a good deal.

## What's here

| Path | What it is |
| --- | --- |
| `tracker.py` | Downloads TCGplayer prices (via tcgcsv.com's daily archives), compares today with 1, 7 and 30 days ago, and writes the data files below. |
| `dashboard/index.html` | The "Pokémon Price Movers" dashboard page (a Claude Data artifact). Reads `movers.json` and `summary.json`. |
| `scanner/index.html` | The "Pokémon Card Scanner" page. Reads `prices.json`; uses Claude to read a card from a photo. |

Generated files (`dashboard/*.json`, `scanner/prices.json`) are not committed;
`tracker.py` rebuilds them.

## Run it

```bash
pip install py7zr
```

```bash
python3 tracker.py
```

Options: `--day-pct` (default 15), `--week-pct` (default 25), `--min-price`
(default 3), `--min-change` (default 1.5).

## How a move gets flagged

A card is flagged when its market price moves at least 15% in a day or 25% in a
week, by at least $1.50, and it's worth at least $3. To filter out one-off odd
sales, the cheapest current listing must have moved the same way (listings more
than 2× or under ½ the market price are ignored as outliers).

## How the scanner judges value

- With an asking price: 15%+ under market is **undervalued**, within 15% is
  **fair**, 15%+ over is **overvalued**.
- Without one: 25%+ above its price 30 days ago is **possibly overvalued**,
  25%+ below is **possibly undervalued**.

Prices are for English cards in Near Mint condition.

## Live pages

- Dashboard: https://claude.ai/artifact/8Sm1FStJgzcjWexBWttYVi
- Scanner: https://claude.ai/artifact/UtG2eNVjfvQfmA1WumUJpg

A daily Claude scheduled task reruns `tracker.py`, refreshes both pages and
sends a phone notification with the day's biggest moves.

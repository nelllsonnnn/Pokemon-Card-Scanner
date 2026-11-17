#!/usr/bin/env python3
"""Fetch official TCGplayer card pictures for recorded transactions that lack one.

Input: a directory of transaction documents, one JSON file per document named
<doc_id>.json (what an ArtifactData "list" with out_dir writes for the scanner's
data/users/me/flips/tx collection).

Output, in OUT_DIR:
  <doc_id>.tx.json    fields to merge into the transaction: cardThumb (small
                      picture) and cardAt, or cardMissing if TCGplayer has none
  <doc_id>.card.json  the large picture, stored as photos/<doc_id>-card
  manifest.json       [{"doc_id", "tx_file", "card_file" or null}]

Usage:  python3 card_images.py TX_DIR OUT_DIR
"""
import base64, glob, json, os, sys, time, urllib.error, urllib.request

CDN = "https://tcgplayer-cdn.tcgplayer.com/product/{pid}_{w}w.jpg"
LIMITS = {200: 60_000, 400: 200_000}  # max data-URL length per size


def fetch(pid, w):
    req = urllib.request.Request(CDN.format(pid=pid, w=w), headers={"User-Agent": "pokeprice-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        if not r.headers.get("Content-Type", "").startswith("image/"):
            raise ValueError("not an image")
        url = "data:image/jpeg;base64," + base64.b64encode(r.read()).decode()
    if len(url) > LIMITS[w]:
        raise ValueError("image too large")
    return url


def main(tx_dir, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    manifest = []
    for path in sorted(glob.glob(os.path.join(tx_dir, "*.json"))):
        doc_id = os.path.basename(path)[:-5]
        t = json.load(open(path))
        pid = t.get("cardId")
        if not isinstance(pid, int) or t.get("cardThumb") or t.get("cardMissing"):
            continue
        entry = {"doc_id": doc_id, "tx_file": os.path.join(out_dir, doc_id + ".tx.json"), "card_file": None}
        try:
            small = fetch(pid, 200)
            update = {"cardThumb": small, "cardAt": int(time.time() * 1000)}
            try:
                big = fetch(pid, 400)
                entry["card_file"] = os.path.join(out_dir, doc_id + ".card.json")
                json.dump({"photo": big}, open(entry["card_file"], "w"))
            except Exception:  # noqa: BLE001 - the small picture is enough
                pass
        except urllib.error.HTTPError as e:
            if e.code not in (403, 404):
                print(f"{doc_id}: TCGplayer error {e.code}, will retry next run")
                continue
            update = {"cardMissing": True}
        except Exception as e:  # noqa: BLE001
            print(f"{doc_id}: {e}, will retry next run")
            continue
        json.dump(update, open(entry["tx_file"], "w"))
        manifest.append(entry)
    json.dump(manifest, open(os.path.join(out_dir, "manifest.json"), "w"), indent=1)
    print(f"{len(manifest)} transaction(s) to update")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

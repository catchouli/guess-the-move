#!/usr/bin/env python3
"""Turn the filter's candidates into the site's puzzle list.

If tools/picks.txt exists, it is the hand-picked order: one position id per
line (blank lines and # comments ignored). Otherwise an automatic order is
used: one position per game, easiest (lowest found depth) first, with the
phases of the game interleaved for variety.

Usage:
  .venv/bin/python tools/build_puzzles.py tools/out/candidates*.json -o site/puzzles.json
"""

import argparse
import json
import os

import chess


def phase(fen):
    b = chess.Board(fen)
    minor_major = sum(len(b.pieces(pt, c)) for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
                      for c in (chess.WHITE, chess.BLACK))
    if minor_major <= 6:
        return "endgame"
    if b.fullmove_number <= 18:
        return "opening"
    return "middlegame"


def slim(p):
    board = chess.Board()
    last = None
    for san in p["history"]:
        last = board.push_san(san)
    assert board.fen() == p["fen"], p["id"]
    return {
        "id": p["id"],
        "fen": p["fen"],
        "lastMove": last.uci() if last else None,
        "history": p["history"],
        "played": p["played"],
        "best": p["best"],
        "tempting": p["tempting"],
        "foundDepth": p["foundDepth"],
        "phase": phase(p["fen"]),
        "moves": {k: v["cp"] for k, v in p["moves"].items()},
        "game": p["game"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("candidates", nargs="+", help="one or more candidates.json files from filter.py")
    ap.add_argument("--picks", default=os.path.join(os.path.dirname(__file__), "picks.txt"))
    ap.add_argument("-o", "--out", default="site/puzzles.json")
    args = ap.parse_args()

    data = {"positions": []}
    by_id = {}
    for path in args.candidates:
        with open(path) as f:
            d = json.load(f)
        data["source"] = d.get("source")
        for p in d["positions"]:
            if p["id"] not in by_id:
                by_id[p["id"]] = p
                data["positions"].append(p)

    if os.path.exists(args.picks):
        with open(args.picks) as f:
            ids = [l.split("#")[0].strip() for l in f]
        chosen = [by_id[i] for i in ids if i]
    else:
        seen_games = set()
        pool = []
        for p in sorted(data["positions"], key=lambda p: (p["foundDepth"], -p["secondBestGap"])):
            g = p["game"]["url"]
            if g in seen_games:
                continue
            seen_games.add(g)
            pool.append(p)
        # Interleave phases, keeping each phase's easy-first order
        buckets = {}
        for p in pool:
            buckets.setdefault(phase(p["fen"]), []).append(p)
        chosen = []
        while any(buckets.values()):
            for k in ("middlegame", "endgame", "opening"):
                if buckets.get(k):
                    chosen.append(buckets[k].pop(0))

    out = {"source": data.get("source"), "puzzles": [slim(p) for p in chosen]}
    with open(args.out, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"{len(chosen)} puzzles -> {args.out}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Annotate candidates with Maia's view: what would a human at 1100/1500/1900 play?

Maia (https://maiachess.com) is a set of Leela nets trained to predict human
moves at a given rating. With one node, lc0 just reads the policy head, so the
policy share of a move is "how likely a player at that rating is to play it".

Adds to each position:
  maia: {"1500": {"top": "e2e4", "played": 0.12, "tempting": 0.34}, ...}

Usage:
  .venv/bin/python tools/maia.py tools/out/candidates.json --weights DIR
"""

import argparse
import glob
import json
import os
import re

import chess
import chess.engine

POLICY_RE = re.compile(r"^(\S+)\s.*\(P:\s*([\d.]+)%\)")


def policy(engine, board):
    """Return {uci: probability} from lc0's verbose move stats at one node."""
    out = {}
    with engine.analysis(board, chess.engine.Limit(nodes=1), game=object()) as an:
        for info in an:
            s = info.get("string")
            if not s:
                continue
            m = POLICY_RE.match(s)
            if m and m.group(1) != "node":
                out[m.group(1)] = float(m.group(2)) / 100
    return out


def lc0_uci(board, uci):
    """lc0's stats may write castling as king-takes-rook (e1h1); normalise to e1g1."""
    fix = {"e1h1": "e1g1", "e1a1": "e1c1", "e8h8": "e8g8", "e8a8": "e8c8"}
    if uci in fix and board.piece_type_at(chess.parse_square(uci[:2])) == chess.KING:
        return fix[uci]
    return uci


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("candidates")
    ap.add_argument("--weights", required=True, help="folder with maia-*.pb.gz")
    ap.add_argument("--lc0", default="lc0")
    args = ap.parse_args()

    with open(args.candidates) as f:
        data = json.load(f)

    for path in sorted(glob.glob(os.path.join(args.weights, "maia-*.pb.gz"))):
        level = re.search(r"maia-(\d+)", path).group(1)
        eng = chess.engine.SimpleEngine.popen_uci([args.lc0, f"--weights={path}"])
        eng.configure({"VerboseMoveStats": True})
        for p in data["positions"]:
            board = chess.Board(p["fen"])
            pol = {lc0_uci(board, k): v for k, v in policy(eng, board).items()}
            top = max(pol, key=pol.get) if pol else None
            p.setdefault("maia", {})[level] = {
                "top": top,
                "played": round(pol.get(p["played"]["uci"], 0), 3),
                "tempting": round(pol.get(p["tempting"]["uci"], 0), 3),
                "topShare": round(pol.get(top, 0), 3) if top else 0,
            }
        eng.quit()
        print(f"maia-{level} done")

    with open(args.candidates, "w") as f:
        json.dump(data, f)


if __name__ == "__main__":
    main()

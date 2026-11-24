#!/usr/bin/env python3
"""Find "guess the move" positions in a month of Lichess elite games.

Pipeline (see PLAN.md):
  1. Book pass: count move-sequence prefixes across every game in the file. A
     position whose move sequence was reached by BOOK_MIN_GAMES or more games
     counts as book (theory, or at least well-trodden).
  2. Candidates: out-of-book plies from human games, skipping checks,
     recaptures and positions with few legal moves.
  3. Quick scan (shallow, multipv 3): drop decided positions and positions
     where the played move is not near the top.
  4. Deep scan (multipv 5, per-depth top move tracked): apply checks 1-4.
  5. Grade: evaluate every legal move of each survivor so the site can grade
     any guess.

Think time (check 5) is not available: the elite database strips clocks.

Usage:
  .venv/bin/python tools/filter.py lichess_elite_2025-09.pgn --games 2000 -o tools/out/candidates.json
"""

import argparse
import json
import multiprocessing as mp
import os
import random
import re
import sys
import time

import chess
import chess.engine
import chess.pgn
import numpy as np

STOCKFISH = os.environ.get("STOCKFISH", "stockfish")

# Thresholds (centipawns, from the side to move). Starting points to tune.
BOOK_MIN_GAMES = 3       # prefix seen in this many games = book
MIN_PLY = 16             # never before move 9
MIN_LEGAL_MOVES = 12
QUICK_DEPTH = 10
MAX_ABS_EVAL = 200       # decided positions are out
DEEP_DEPTH = 16
RIGHT_MARGIN = 20        # check 1: played move within this of the top line
TRAP_MARGIN = 100        # check 3: tempting move at least this much worse
REASONABLE_MARGIN = 100  # check 4: moves within this of best count as reasonable
MIN_REASONABLE = 3       # check 4: at least this many reasonable moves
UNIQUE_GAP = 40          # "no lesson" guard: next best alternative this much worse
MIN_FOUND_DEPTH = 4      # check 2: shallow search must disagree up to here
MAX_FOUND_DEPTH = 14     # found only deeper than this = brute force
GRADE_DEPTH = 14
MAX_CANDIDATES_PER_GAME = 12
MATE_CP = 10000


def cp(score: chess.engine.PovScore, turn: chess.Color) -> int:
    return score.pov(turn).score(mate_score=MATE_CP)


# ---------------------------------------------------------------- PGN reading

HEADER_RE = re.compile(r'^\[(\w+) "(.*)"\]$')
MOVENUM_RE = re.compile(r"\d+\.(\.\.)?")
RESULTS = {"1-0", "0-1", "1/2-1/2", "*"}


def iter_games(path):
    """Yield (headers, san_tokens) quickly, without building boards."""
    headers, moves = {}, []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("["):
                if moves:
                    yield headers, moves
                    headers, moves = {}, []
                m = HEADER_RE.match(line)
                if m:
                    headers[m.group(1)] = m.group(2)
            else:
                line = re.sub(r"\{[^}]*\}", " ", line)
                moves.extend(t for t in MOVENUM_RE.sub(" ", line).split() if t not in RESULTS)
    if moves:
        yield headers, moves


def is_human_game(h):
    return "BOT" not in (h.get("WhiteTitle", ""), h.get("BlackTitle", "")) and h.get("Variant", "Standard") == "Standard" \
        and "FEN" not in h


def prefix_hashes(moves, max_ply):
    out, acc = [], 1469598103934665603
    for tok in moves[:max_ply]:
        acc = hash((acc, tok)) & 0xFFFFFFFFFFFFFFFF
        out.append(acc)
    return out


# ---------------------------------------------------------------- engine work

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH)
        _engine.configure({"Threads": 1, "Hash": 64})
    return _engine


def deep_scan(board, depth):
    """multipv 3 to `depth`. Returns (lines, top_by_depth)."""
    eng = get_engine()
    top_by_depth = {}
    lines = {}
    with eng.analysis(board, chess.engine.Limit(depth=depth), multipv=3, game=object()) as an:
        for info in an:
            if "pv" not in info or "depth" not in info or "score" not in info:
                continue
            if info.get("lowerbound") or info.get("upperbound"):
                continue
            mpv = info.get("multipv", 1)
            if mpv == 1:
                top_by_depth[info["depth"]] = info["pv"][0]
            if info["depth"] == depth:
                lines[mpv] = info
    lines = [lines[k] for k in sorted(lines)]
    return lines, top_by_depth


def eval_move(board, move, depth):
    eng = get_engine()
    info = eng.analyse(board, chess.engine.Limit(depth=depth), root_moves=[move], game=object())
    return cp(info["score"], board.turn), info.get("pv", [move])


def san_line(board, pv, limit=10):
    b = board.copy()
    out = []
    for mv in pv[:limit]:
        if mv not in b.legal_moves:
            break
        out.append(b.san(mv))
        b.push(mv)
    return out


def grade_all(board, depth):
    eng = get_engine()
    n = board.legal_moves.count()
    infos = eng.analyse(board, chess.engine.Limit(depth=depth), multipv=n, game=object())
    graded = {}
    for info in infos:
        if "pv" not in info:
            continue
        mv = info["pv"][0]
        graded[mv.uci()] = {"san": board.san(mv), "cp": cp(info["score"], board.turn)}
    return graded


def scan_game(task):
    headers, moves, book_end = task
    board = chess.Board()
    sans = []
    candidates = []
    last_capture_sq = None
    for ply, san in enumerate(moves):
        try:
            mv = board.parse_san(san)
        except ValueError:
            return [], {}
        is_cap = board.is_capture(mv)
        if ply >= max(book_end, MIN_PLY) and ply < len(moves) - 2:
            recapture = is_cap and mv.to_square == last_capture_sq
            if not recapture and not board.is_check() and not board.gives_check(mv) \
                    and board.legal_moves.count() >= MIN_LEGAL_MOVES:
                candidates.append((ply, board.fen(), mv, list(sans)))
        last_capture_sq = mv.to_square if is_cap else None
        sans.append(san)
        board.push(mv)

    random.Random(headers.get("LichessURL", "")).shuffle(candidates)
    results = []
    stats = {}
    eng = get_engine()
    for ply, fen, played, history in candidates[:MAX_CANDIDATES_PER_GAME]:
        b = chess.Board(fen)
        r = check_position(eng, b, played)
        if isinstance(r, str):
            stats[r] = stats.get(r, 0) + 1
            continue
        stats["pass"] = stats.get("pass", 0) + 1
        r.update({
            "id": f"{headers.get('LichessURL', '').rsplit('/', 1)[-1]}-{ply}",
            "fen": fen,
            "ply": ply,
            "history": history,
            "game": {
                "white": headers.get("White"), "black": headers.get("Black"),
                "whiteElo": headers.get("WhiteElo"), "blackElo": headers.get("BlackElo"),
                "date": headers.get("Date"), "timeControl": headers.get("TimeControl"),
                "url": headers.get("LichessURL"), "result": headers.get("Result"),
                "opening": headers.get("Opening"),
            },
        })
        results.append(r)
    return results, stats


def check_position(eng, board, played):
    turn = board.turn
    # Quick scan
    quick = eng.analyse(board, chess.engine.Limit(depth=QUICK_DEPTH), multipv=3, game=object())
    best_q = cp(quick[0]["score"], turn)
    if abs(best_q) > MAX_ABS_EVAL:
        return "decided_quick"
    if played not in [i["pv"][0] for i in quick if "pv" in i]:
        return "played_not_top3_quick"

    # Deep scan
    lines, top_by_depth = deep_scan(board, DEEP_DEPTH)
    if len(lines) < MIN_REASONABLE:
        return "few_lines"
    evals = [(l["pv"][0], cp(l["score"], turn), l["pv"]) for l in lines]
    best_cp = evals[0][1]
    if abs(best_cp) > MAX_ABS_EVAL:
        return "decided_deep"
    played_cp = next((e[1] for e in evals if e[0] == played), None)
    # Check 1: right
    if played_cp is None or played_cp < best_cp - RIGHT_MARGIN:
        return "check1_not_best"
    # "No lesson" guard: next best alternative clearly worse
    others = [e for e in evals if e[0] != played]
    if not others or played_cp - others[0][1] < UNIQUE_GAP:
        return "no_unique"
    # Check 4: not forced
    if sum(1 for e in evals if e[1] >= best_cp - REASONABLE_MARGIN) < MIN_REASONABLE:
        return "check4_forced"
    # Check 2: non-obvious. found_depth = first depth from which the played
    # move stays on top.
    depths = sorted(top_by_depth)
    found_depth = None
    for d in depths:
        if all(top_by_depth[x] == played for x in depths if x >= d):
            found_depth = d
            break
    if found_depth is None or found_depth <= MIN_FOUND_DEPTH or found_depth > MAX_FOUND_DEPTH:
        return "check2_obvious"
    shallow = [top_by_depth[d] for d in depths if d < found_depth and top_by_depth[d] != played]
    if not shallow:
        return "check2_no_shallow"
    # Tempting move: the shallow favourite (most often top below found_depth,
    # ties to the deepest).
    counts = {}
    for d in depths:
        if d < found_depth and top_by_depth[d] != played:
            counts[top_by_depth[d]] = (counts.get(top_by_depth[d], (0, 0))[0] + 1, d)
    tempting = max(counts, key=lambda m: counts[m])
    # Check 3: trap
    t = next((e for e in evals if e[0] == tempting), None)
    if t is None:
        t_cp, t_pv = eval_move(board, tempting, DEEP_DEPTH)
    else:
        t_cp, t_pv = t[1], t[2]
    if played_cp - t_cp < TRAP_MARGIN:
        return "check3_no_trap"

    graded = grade_all(board, GRADE_DEPTH)
    # Deep evals override the graded ones for the moves we know better
    for mv, c, _ in evals:
        if mv.uci() in graded:
            graded[mv.uci()]["cp"] = c
    graded[tempting.uci()]["cp"] = t_cp

    played_pv = next(e[2] for e in evals if e[0] == played)
    return {
        "played": {"uci": played.uci(), "san": board.san(played), "cp": played_cp, "line": san_line(board, played_pv)},
        "best": {"uci": evals[0][0].uci(), "san": board.san(evals[0][0]), "cp": best_cp, "line": san_line(board, evals[0][2])},
        "tempting": {"uci": tempting.uci(), "san": board.san(tempting), "cp": t_cp, "line": san_line(board, t_pv),
                     "depths": [d for d in depths if d < found_depth and top_by_depth[d] == tempting]},
        "foundDepth": found_depth,
        "secondBestGap": played_cp - others[0][1],
        "reasonable": sum(1 for e in evals if e[1] >= best_cp - REASONABLE_MARGIN),
        "moves": graded,
        "isCapture": board.is_capture(played),
    }


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pgn")
    ap.add_argument("--games", type=int, default=1000, help="games to engine-scan")
    ap.add_argument("--min-base", type=int, default=180, help="minimum base time (s)")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--offset", type=int, default=0, help="skip this many games of the shuffled list (to extend an earlier run)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("-o", "--out", default="tools/out/candidates.json")
    args = ap.parse_args()

    t0 = time.time()
    print("Book pass...", file=sys.stderr)
    all_games = []
    hashes = []
    for h, moves in iter_games(args.pgn):
        ph = prefix_hashes(moves, 40)
        hashes.extend(ph)
        if is_human_game(h):
            base = int(h.get("TimeControl", "0+0").split("+")[0] or 0) if h.get("TimeControl", "-") != "-" else 0
            if base >= args.min_base and len(moves) >= 40:
                all_games.append((h, moves, ph))
    arr = np.array(hashes, dtype=np.uint64)
    uniq, counts = np.unique(arr, return_counts=True)
    print(f"  {len(hashes)} prefixes, {len(all_games)} eligible games, {time.time() - t0:.0f}s", file=sys.stderr)

    rng = random.Random(args.seed)
    rng.shuffle(all_games)
    tasks = []
    for h, moves, ph in all_games[args.offset:args.offset + args.games]:
        idx = np.searchsorted(uniq, np.array(ph, dtype=np.uint64))
        c = counts[idx]
        # book_end: first ply whose position (prefix before it) is rare.
        # Position before ply i is prefix i-1 (i.e. moves[:i]).
        book_end = len(moves)
        for i in range(1, len(ph)):
            if c[i - 1] < BOOK_MIN_GAMES:
                book_end = i
                break
        tasks.append((h, moves, book_end))
    del hashes, arr

    print(f"Engine pass over {len(tasks)} games with {args.workers} workers...", file=sys.stderr)
    results = []
    stats = {}
    done = 0
    with mp.Pool(args.workers) as pool:
        for res, st in pool.imap_unordered(scan_game, tasks, chunksize=1):
            done += 1
            results.extend(res)
            for k, v in st.items():
                stats[k] = stats.get(k, 0) + v
            if done % 25 == 0:
                print(f"  {done}/{len(tasks)} games, {len(results)} positions, {time.time() - t0:.0f}s", file=sys.stderr)
                print("   ", dict(sorted(stats.items(), key=lambda kv: -kv[1])), file=sys.stderr)

    results.sort(key=lambda r: (r["foundDepth"], -r["secondBestGap"]))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump({"source": os.path.basename(args.pgn), "gamesScanned": len(tasks), "positions": results}, f)
    print(f"{len(results)} positions from {len(tasks)} games -> {args.out} ({time.time() - t0:.0f}s)", file=sys.stderr)
    print("Rejections:", dict(sorted(stats.items(), key=lambda kv: -kv[1])), file=sys.stderr)


if __name__ == "__main__":
    main()

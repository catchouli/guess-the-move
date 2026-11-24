# Guess the move

A Wordle-style daily chess page. Each day shows one position from a real strong game. You play the move you would make, it is graded against what was actually played, and the reveal explains why. Working title.

## The game

- One position a day, everyone gets the same one.
- You make a move on the board. It is graded, not right/wrong.
- The reveal shows the played move, the engine's best line, and the refutation of the tempting move.
- A shareable result grid and a streak. No account needed if progress stays in localStorage.

## What makes a position interesting

Not obvious, but findable. All three must hold:

- There is a tempting wrong move.
- There is a clearly right move.
- The strong player had to think to find it.

Positions that fail this:

| Fails because | Example |
|---|---|
| Memorised, not reasoned | Still in the opening book |
| Forced | Only one legal or reasonable move: recaptures, only-moves |
| No right answer to reward | The player chose something the engine rejects |
| The player erred | The played move is not actually good |
| No lesson in it | Several moves are equally good |
| The move does not matter | The game is already won or lost |
| Brute force, not judgement | Only findable by searching many plies |

## Selection pipeline

An offline script (Python, python-chess, Stockfish over UCI): candidates, engine scoring, shortlist, hand pick.

### Candidates

- Source: the Lichess elite database (CC0, monthly PGNs of games between players rated 2200+).
- Skip positions still in the opening book (Lichess opening explorer, or a local book).
- Skip decided positions: absolute eval above about 2 pawns.
- Optional later: positions from instructive-chess, where the master's commentary could be shown in the reveal. Licensing to think about first.

### Engine scoring

Run Stockfish multiPV (5 lines) at a fixed depth, one thread, fixed hash, so runs are reproducible. Keep the position only if every check passes. Thresholds are starting points to tune.

| # | Check | Starting threshold |
|---|---|---|
| 1 | Right: the played move is the engine's top move, or level with it | Within 0.2 of the top line |
| 2 | Non-obvious: a shallow search prefers a different, natural move | Depth 2 to 8 top move differs from the played move |
| 3 | Trap: that tempting move is clearly worse | At least 1.0 below the played move |
| 4 | Not forced: several reasonable moves | At least 3 legal moves within 1.0 of the best; the played move is not a check or a recapture |
| 5 | A real decision: the player spent time on it | Think time above a threshold |

Notes on two of them:

- **Found at depth N.** The depth at which the played move first becomes the top move is a free difficulty dial. Found around depth 4: a lesson in judgement. Found at depth 18 or more: probably brute force, exclude.
- **Think time.** Lichess PGNs carry a clock per move (`%clk`). Think time is the drop in the player's own clock between two of their moves, minus the increment.

### Shortlist and hand pick

- The filter only ranks. Hand-pick and order the first ~100, starting easy. Wordle's feel came from a hand-ordered list, not an algorithm.
- Keep variety across game phase, material balance, quiet move against capture, and type of trap.

### Data loop after launch

- Record every guess (move, time spent).
- Success rate per position: above about 80% is too easy, below about 10% is too hard. Adjust the thresholds.
- Check what players actually guessed against the tempting move the filter predicted. That validates check 2.
- Give positions a rating, like puzzle Elo, and pick each day's position for a target difficulty.

## Scoring a guess

- Grade by eval: compare the eval of the player's move with the eval of the best move. Near misses get partial credit.
- Tiers for the usual inaccuracy, mistake and blunder bands, plus a top tier for the played move itself.
- The share grid is one coloured square per tier, so results compare between players.

## MVP

1. Filter script: one elite month in, a JSON of shortlisted positions with engine lines out.
2. Eyeball what it picks. Tune the thresholds.
3. Static page: board, make a move, score, reveal. Positions come from the precomputed JSON, one per day. GitHub Pages.
4. Share text.

## Tech sketch

- Filter: Python, python-chess, Stockfish.
- Site: plain HTML and JS, chess.js for the rules, a board renderer, no backend.

## Open questions

- Is shallow Stockfish a good stand-in for "obvious to a human"? With NNUE it is far stronger than a club player even at low depth. Alternatives: a human-like model (Maia), or popularity data (how often strong players chose each move in that position).
- Yield: what fraction of positions passes all five checks? That decides how many games are needed per day of content.
- Allow days where the played move is the engine's second choice but still good? More human days, less clean answers.
- Reveal text: engine line only, or generate an explanation too?
- Name and domain.

## Next step

Prototype the filter on one month of elite games and look at what it picks.

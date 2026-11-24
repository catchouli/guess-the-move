# Guess the Move

A daily chess position from a real game between strong players. Play the move you think they played, get graded on it, then see what they actually played, the tempting move that doesn't work, and why.

Prototype. See [PLAN.md](PLAN.md) for the idea.

## Layout

- `site/`: the static page (plain HTML and JS, no build step). Deployed to GitHub Pages from `main`.
  - `index.html`, `app.js`, `style.css`: the game.
  - `review.html`: every shortlisted position on one page, for hand-picking.
  - `puzzles.json`: the puzzle list, generated.
  - `vendor/`: [cm-chessboard](https://github.com/shaack/cm-chessboard) (MIT) and [chess.js](https://github.com/jhlywa/chess.js) (BSD-2).
- `tools/filter.py`: finds candidate positions in a month of the [Lichess Elite Database](https://database.nikonoel.fr/).
- `tools/build_puzzles.py`: turns candidates into `site/puzzles.json`, in `tools/picks.txt` order if that exists.

## Making puzzles

```sh
brew install stockfish
python3 -m venv .venv && .venv/bin/pip install chess numpy

# a month of elite games
curl -O https://database.nikonoel.fr/lichess_elite_2025-09.zip && unzip lichess_elite_2025-09.zip

.venv/bin/python tools/filter.py lichess_elite_2025-09.pgn --games 800 -o tools/out/candidates.json
.venv/bin/python tools/build_puzzles.py tools/out/candidates*.json -o site/puzzles.json
```

`--offset N` skips the first N games of the (seeded) shuffle, so a second run can add more positions without repeating the first.

To run the page locally: `python3 -m http.server -d site` and open http://localhost:8000.

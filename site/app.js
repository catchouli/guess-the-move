import {Chessboard, COLOR, INPUT_EVENT_TYPE, BORDER_TYPE} from "./vendor/cm-chessboard/Chessboard.js"
import {Markers, MARKER_TYPE} from "./vendor/cm-chessboard/extensions/markers/Markers.js"
import {Arrows, ARROW_TYPE} from "./vendor/cm-chessboard/extensions/arrows/Arrows.js"
import {PromotionDialog, PROMOTION_DIALOG_RESULT_TYPE} from "./vendor/cm-chessboard/extensions/promotion-dialog/PromotionDialog.js"
import {Chess} from "./vendor/chess.js/chess.js"

// ------------------------------------------------------------------ config

const MAX_TRIES = 3
const EPOCH = [2026, 10, 24] // puzzle #1 (year, month 0-based, day)
const STORE = "gtm:v1:"

// Tiers by drop in win chance (percentage points) against the best move.
// The game move itself is always the top tier.
const TIERS = [
  {key: "move", square: "🟩", label: "The game move!"},
  {key: "excellent", max: 4, square: "🟨", label: "Excellent, but not the game move"},
  {key: "good", max: 10, square: "🟧", label: "Playable, but there's better"},
  {key: "mistake", max: 20, square: "🟥", label: "Mistake"},
  {key: "blunder", max: Infinity, square: "⬛", label: "Blunder"},
]
const PIECE_NAMES = {p: "pawn", n: "knight", b: "bishop", r: "rook", q: "queen", k: "king"}

// ------------------------------------------------------------------ helpers

const $ = (id) => document.getElementById(id)
const winPct = (cp) => 50 + 50 * (2 / (1 + Math.exp(-0.00368208 * cp)) - 1)
const fmtEval = (cp) => Math.abs(cp) >= 9000
  ? (cp > 0 ? "mate" : "getting mated")
  : (cp >= 0 ? "+" : "−") + (Math.abs(cp) / 100).toFixed(1)

function todayNumber() {
  const now = new Date()
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())
  return Math.floor((today - Date.UTC(...EPOCH)) / 86400000) + 1
}

function dateForNumber(n) {
  const d = new Date(Date.UTC(...EPOCH) + (n - 1) * 86400000)
  return d.toLocaleDateString(undefined, {day: "numeric", month: "short", year: "numeric", timeZone: "UTC"})
}

function load(key, fallback) {
  try {
    const v = localStorage.getItem(STORE + key)
    return v ? JSON.parse(v) : fallback
  } catch { return fallback }
}

function save(key, value) {
  try { localStorage.setItem(STORE + key, JSON.stringify(value)) } catch { /* private mode */ }
}

function grade(p, uci) {
  if (uci === p.played.uci) return {...TIERS[0], loss: 0, cp: p.played.cp}
  const best = Math.max(...Object.values(p.moves))
  const cp = p.moves[uci] ?? -10000
  const loss = winPct(best) - winPct(cp)
  const tier = TIERS.slice(1).find(t => loss <= t.max)
  return {...tier, loss, cp, trap: uci === p.tempting.uci}
}

// SAN list with move numbers, starting from a FEN.
function numbered(fen, sans) {
  const [, turn, , , , full] = fen.split(" ")
  let n = parseInt(full, 10)
  let white = turn === "w"
  return sans.map((san, i) => {
    let prefix = ""
    if (white) prefix = `${n}.`
    else if (i === 0) prefix = `${n}…`
    if (!white) n++
    white = !white
    return {prefix, san}
  })
}

const moveText = (fen, sans) => numbered(fen, sans).map(m => m.prefix + m.san).join(" ")

// ------------------------------------------------------------------ state

let puzzles = []
let number = 1     // puzzle number being shown
let puzzle = null
let state = null   // {guesses: [uci], done: bool}
let chess = null
let board = null
let busy = false

async function main() {
  const res = await fetch("puzzles.json")
  puzzles = (await res.json()).puzzles

  board = new Chessboard($("board"), {
    assetsUrl: "./vendor/cm-chessboard/assets/",
    style: {cssClass: "gtm", borderType: BORDER_TYPE.none, animationDuration: 220, showCoordinates: true},
    extensions: [
      {class: Markers, props: {autoMarkers: MARKER_TYPE.square}},
      {class: Arrows},
      {class: PromotionDialog},
    ],
  })

  const param = parseInt(new URLSearchParams(location.search).get("n"), 10)
  show(Number.isFinite(param) ? param : todayNumber())

  $("prev").onclick = () => show(number - 1)
  $("next").onclick = () => show(number + 1)
  window.addEventListener("popstate", () => {
    const n = parseInt(new URLSearchParams(location.search).get("n"), 10)
    show(Number.isFinite(n) ? n : todayNumber(), false)
  })
}

function show(n, push = true) {
  n = Math.max(1, Math.min(n, puzzles.length))
  number = n
  puzzle = puzzles[(n - 1) % puzzles.length]
  state = load("p:" + puzzle.id, {guesses: [], done: false})
  if (push) {
    const url = n === todayNumber() ? location.pathname : `?n=${n}`
    history.pushState(null, "", url)
  }

  $("day-label").textContent = `#${n} · ${dateForNumber(n)}${n === todayNumber() ? " · today" : ""}`
  $("prev").disabled = n <= 1
  $("next").disabled = n >= puzzles.length

  chess = new Chess(puzzle.fen)
  const side = chess.turn() === "w" ? COLOR.white : COLOR.black
  const sideName = side === COLOR.white ? "White" : "Black"
  const player = side === COLOR.white ? puzzle.game.white : puzzle.game.black
  const elo = side === COLOR.white ? puzzle.game.whiteElo : puzzle.game.blackElo
  const plies = puzzle.history.length
  const lastFull = plies ? `${Math.ceil(plies / 2)}${plies % 2 ? "." : "…"}${puzzle.history[plies - 1]}` : "the start"

  $("prompt-main").innerHTML = `${sideName} to play. What did <strong>${esc(player)}</strong> <span class="elo">(${elo})</span> play?`
  $("prompt-sub").textContent = `After ${lastFull} · ${puzzle.game.white} vs ${puzzle.game.black} · ${tcName(puzzle.game.timeControl)}, ${puzzle.game.date.slice(0, 4)}`

  board.setOrientation(side)
  resetBoard(false)
  renderTries()
  $("feedback").textContent = ""
  $("feedback").className = "feedback"
  $("hint").textContent = ""
  $("reveal").hidden = true
  $("reveal").innerHTML = ""
  document.body.classList.remove("revealed")

  if (state.done) {
    finish(false)
  } else {
    enableInput()
    showHints()
  }
}

function tcName(tc) {
  const [base, inc] = (tc || "0+0").split("+").map(Number)
  const est = base + 40 * inc
  const kind = est < 180 ? "Bullet" : est < 480 ? "Blitz" : est < 1500 ? "Rapid" : "Classical"
  return `${kind} ${base / 60}+${inc}`
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]))
}

function resetBoard(animated = true) {
  chess = new Chess(puzzle.fen)
  board.removeArrows()
  board.removeMarkers()
  board.setPosition(puzzle.fen, animated)
  markLastMove()
}

function markLastMove() {
  board.removeMarkers(MARKER_TYPE.square)
  if (puzzle.lastMove) {
    board.addMarker(MARKER_TYPE.square, puzzle.lastMove.slice(0, 2))
    board.addMarker(MARKER_TYPE.square, puzzle.lastMove.slice(2, 4))
  }
}

// ------------------------------------------------------------------ input

function enableInput() {
  const color = chess.turn() === "w" ? COLOR.white : COLOR.black
  board.enableMoveInput(onInput, color)
}

function onInput(event) {
  if (busy) return false
  if (event.type === INPUT_EVENT_TYPE.movingOverSquare) return
  if (event.type !== INPUT_EVENT_TYPE.moveInputFinished) board.removeLegalMovesMarkers()

  if (event.type === INPUT_EVENT_TYPE.moveInputStarted) {
    const moves = chess.moves({square: event.squareFrom, verbose: true})
    board.addLegalMovesMarkers(moves)
    return moves.length > 0
  }
  if (event.type === INPUT_EVENT_TYPE.validateMoveInput) {
    const from = event.squareFrom, to = event.squareTo
    const legal = chess.moves({square: from, verbose: true}).filter(m => m.to === to)
    if (!legal.length) return false
    if (legal.some(m => m.promotion)) {
      const color = chess.turn() === "w" ? COLOR.white : COLOR.black
      board.showPromotionDialog(to, color, (result) => {
        if (result.type === PROMOTION_DIALOG_RESULT_TYPE.pieceSelected) {
          submit(from + to + result.piece.charAt(1))
        } else {
          resetBoard(true)
          enableInput()
        }
      })
      return true
    }
    // Let the board finish its own move animation, then grade.
    queueMicrotask(() => submit(from + to))
    return true
  }
}

async function submit(uci) {
  if (busy || state.done) return
  busy = true
  board.disableMoveInput()
  const move = chess.move({from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4]})
  await board.setPosition(chess.fen(), true)

  state.guesses.push(uci)
  const g = grade(puzzle, uci)
  showFeedback(g, move.san)
  renderTries()

  const solved = g.key === "move"
  if (solved || state.guesses.length >= MAX_TRIES) {
    state.done = true
    save("p:" + puzzle.id, state)
    await wait(700)
    busy = false
    finish(true)
    return
  }
  save("p:" + puzzle.id, state)
  await wait(1100)
  resetBoard(true)
  busy = false
  enableInput()
  showHints()
}

const wait = (ms) => new Promise(r => setTimeout(r, ms))

function showFeedback(g, san) {
  const el = $("feedback")
  let text = `${san}: ${g.label}`
  if (g.key !== "move") text += ` (${fmtEval(g.cp)})`
  if (g.trap) text += " 🪤 That's the tempting move!"
  el.textContent = text
  el.className = "feedback tier-" + g.key
}

function showHints() {
  const misses = state.done ? 0 : state.guesses.length
  const from = puzzle.played.uci.slice(0, 2)
  const piece = PIECE_NAMES[new Chess(puzzle.fen).get(from).type]
  let text = ""
  if (misses === 1) text = `Hint: it's a ${piece} move.`
  if (misses >= 2) {
    text = `Hint: it's the ${piece} on the circled square.`
    board.addMarker(MARKER_TYPE.circlePrimary, from)
  }
  $("hint").textContent = text
}

function renderTries() {
  const el = $("tries")
  el.innerHTML = ""
  for (let i = 0; i < MAX_TRIES; i++) {
    const slot = document.createElement("div")
    slot.className = "try"
    const uci = state.guesses[i]
    if (uci) {
      const g = grade(puzzle, uci)
      const c = new Chess(puzzle.fen)
      const san = c.move({from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4]}).san
      slot.classList.add("tier-" + g.key)
      slot.innerHTML = `<span class="try-san">${esc(san)}</span>`
      slot.title = g.label
    } else {
      slot.classList.add("empty")
    }
    el.appendChild(slot)
  }
}

// ------------------------------------------------------------------ reveal

function finish(justNow) {
  board.disableMoveInput()
  $("hint").textContent = ""
  const p = puzzle
  const solved = state.guesses.includes(p.played.uci)
  resetBoard(justNow)
  board.addArrow(ARROW_TYPE.success, p.played.uci.slice(0, 2), p.played.uci.slice(2, 4))
  if (p.tempting.uci !== p.played.uci) {
    board.addArrow(ARROW_TYPE.danger, p.tempting.uci.slice(0, 2), p.tempting.uci.slice(2, 4))
  }

  const side = p.fen.split(" ")[1] === "w" ? "White" : "Black"
  const player = side === "White" ? p.game.white : p.game.black
  const fb = $("feedback")
  fb.textContent = solved
    ? `Solved in ${state.guesses.indexOf(p.played.uci) + 1}/${MAX_TRIES} 🎉`
    : `The game move was ${p.played.san}.`
  fb.className = "feedback " + (solved ? "tier-move" : "tier-none")

  const temptingGraded = grade(p, p.tempting.uci)
  const diff = difficulty(p)
  const sameAsBest = p.best.uci === p.played.uci

  const r = $("reveal")
  r.innerHTML = `
    <div class="card">
      <h2><span class="dot ok"></span>${esc(player)} played ${moveChip(p.played.san)}</h2>
      <p>${sameAsBest ? "It's also Stockfish's top choice" : `Stockfish rates it level with its top choice, ${esc(p.best.san)}`}, at ${fmtEval(p.played.cp)} for ${side}.</p>
      <p class="line-label">Engine line</p>
      ${lineHtml(p.fen, p.played.line, "played")}
    </div>
    <div class="card">
      <h2><span class="dot bad"></span>The tempting ${moveChip(p.tempting.san)}</h2>
      <p>${temptText(p, temptingGraded)}</p>
      <p class="line-label">Refutation</p>
      ${lineHtml(p.fen, p.tempting.line, "tempting")}
    </div>
    <div class="card meta">
      <p><strong>Difficulty:</strong> ${diff.label} <span class="muted">(${diff.detail})</span></p>
      <p><strong>Game:</strong> ${esc(p.game.white)} (${p.game.whiteElo}) vs ${esc(p.game.black)} (${p.game.blackElo}), ${tcName(p.game.timeControl)}, ${esc(p.game.date)}. Result ${esc(p.game.result)}.
        <a href="${esc(p.game.url)}#${p.history.length}" target="_blank" rel="noopener">Open on Lichess ↗</a></p>
      <details><summary>Moves to here</summary><p class="mono">${esc(moveText(new Chess().fen(), p.history))}</p></details>
    </div>
    <div class="share-row">
      <button id="share" class="btn primary">Share result</button>
      <button id="reset-view" class="btn">Back to puzzle</button>
      ${number < puzzles.length ? `<button id="next-puzzle" class="btn">Next puzzle ›</button>` : ""}
    </div>
    <pre id="share-preview" class="share-preview">${esc(shareText())}</pre>
  `
  r.hidden = false
  document.body.classList.add("revealed")

  r.querySelectorAll("[data-line]").forEach(el => {
    el.addEventListener("click", () => stepTo(el.dataset.line, parseInt(el.dataset.i, 10)))
  })
  $("share").onclick = share
  $("reset-view").onclick = () => { highlightStep(null); finishBoard() }
  if ($("next-puzzle")) $("next-puzzle").onclick = () => { show(number + 1); window.scrollTo({top: 0, behavior: "smooth"}) }
}

function finishBoard() {
  resetBoard(true)
  board.addArrow(ARROW_TYPE.success, puzzle.played.uci.slice(0, 2), puzzle.played.uci.slice(2, 4))
  if (puzzle.tempting.uci !== puzzle.played.uci) {
    board.addArrow(ARROW_TYPE.danger, puzzle.tempting.uci.slice(0, 2), puzzle.tempting.uci.slice(2, 4))
  }
}

function moveChip(san) {
  return `<span class="move-chip">${esc(san)}</span>`
}

function rangeText(depths) {
  if (!depths || !depths.length) return "low depth"
  const lo = Math.min(...depths), hi = Math.max(...depths)
  return lo === hi ? `${lo}` : `${lo}–${hi}`
}

function maiaMean(p, key) {
  const v = Object.values(p.maia)
  return v.reduce((a, x) => a + x[key], 0) / v.length
}

const pct = (x) => `${Math.round(x * 100)}%`

function temptText(p, g) {
  const after = `but it's ${fmtEval(p.tempting.cp)} after the line below: ${g.key === "blunder" ? "a blunder" : `a ${g.label.toLowerCase()}`}.`
  if (p.maia && p.maia["1500"]) {
    return `Maia, a model trained to play like humans, expects ${pct(p.maia["1500"].tempting)} of 1500-rated players to play it ` +
      `(and only ${pct(p.maia["1500"].played)} to find ${esc(p.played.san)}), ${after}`
  }
  return `A quick search prefers it (Stockfish's favourite at depth ${rangeText(p.tempting.depths)}), ${after}`
}

function difficulty(p) {
  if (p.maia) {
    const m = maiaMean(p, "played")
    const label = m >= 0.2 ? "Gentle" : m >= 0.12 ? "Tricky" : m >= 0.06 ? "Hard" : "Fiendish"
    const levels = Object.entries(p.maia).map(([lvl, v]) => `${pct(v.played)} at ${lvl}`).join(", ")
    return {label, detail: `how often Maia expects humans to find ${p.played.san}: ${levels}`}
  }
  const d = p.foundDepth
  const label = d <= 6 ? "Gentle" : d <= 9 ? "Tricky" : d <= 12 ? "Hard" : "Fiendish"
  return {label, detail: `Stockfish settles on ${p.played.san} from depth ${d}`}
}

function lineHtml(fen, sans, name) {
  return `<p class="line">${numbered(fen, sans).map((m, i) =>
    `<button class="step" data-line="${name}" data-i="${i}">${m.prefix ? `<span class="num">${m.prefix}</span>` : ""}${esc(m.san)}</button>`
  ).join(" ")}</p>`
}

function stepTo(name, i) {
  const sans = name === "played" ? puzzle.played.line : puzzle.tempting.line
  const c = new Chess(puzzle.fen)
  let last = null
  for (let k = 0; k <= i; k++) last = c.move(sans[k])
  board.removeArrows()
  board.removeMarkers()
  board.setPosition(c.fen(), true)
  if (last) {
    board.addMarker(MARKER_TYPE.square, last.from)
    board.addMarker(MARKER_TYPE.square, last.to)
  }
  highlightStep(name, i)
}

function highlightStep(name, i) {
  document.querySelectorAll(".step.active").forEach(el => el.classList.remove("active"))
  if (name) document.querySelector(`.step[data-line="${name}"][data-i="${i}"]`)?.classList.add("active")
}

// ------------------------------------------------------------------ share

function shareText() {
  const squares = state.guesses.map(u => grade(puzzle, u).square).join("")
  const solved = state.guesses.includes(puzzle.played.uci)
  const score = solved ? `${state.guesses.indexOf(puzzle.played.uci) + 1}/${MAX_TRIES}` : `X/${MAX_TRIES}`
  return `Guess the Move #${number} ${score}\n${squares}`
}

async function share() {
  const text = shareText() + "\n" + location.origin + location.pathname + (number === todayNumber() ? "" : `?n=${number}`)
  try {
    if (navigator.share && matchMedia("(pointer: coarse)").matches) {
      await navigator.share({text})
    } else {
      await navigator.clipboard.writeText(text)
      $("share").textContent = "Copied ✓"
      setTimeout(() => { if ($("share")) $("share").textContent = "Share result" }, 1500)
    }
  } catch { /* user cancelled */ }
}

main().catch(err => {
  console.error(err)
  $("prompt-main").textContent = "Couldn't load today's puzzle."
})

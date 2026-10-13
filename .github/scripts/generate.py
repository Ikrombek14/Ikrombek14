#!/usr/bin/env python3
"""Generate profile SVGs for a fixed calendar year.

Outputs (in dist/):
  github-contribution-grid-snake.svg       snake animation, light theme
  github-contribution-grid-snake-dark.svg  snake animation, dark theme
  activity-graph.svg                       daily contribution line chart

Env:
  GITHUB_TOKEN  token for the GraphQL API (Actions provides it)
  GH_USER       GitHub login (default: repository owner)
  YEAR          calendar year to draw (default: current year)
  SAMPLE_DATA   optional path to a JSON {date: count} file, skips the API
"""
import datetime as dt
import json
import os
import urllib.request

USER = os.environ.get("GH_USER") or os.environ.get("GITHUB_REPOSITORY_OWNER", "Ikrombek14")
YEAR = int(os.environ.get("YEAR") or dt.date.today().year)
OUT = os.environ.get("OUT_DIR", "dist")

CELL, GAP = 12, 3
STEP = CELL + GAP
PAD_X, PAD_Y = 20, 34
STEP_SEC = 0.12          # time the snake needs per grid step
SNAKE_LEN = 5

THEMES = {
    "light": {
        "levels": ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"],
        "snake": "#8250df",
        "border": "#1b1f230a",
        "text": "#57606a",
    },
    "dark": {
        "levels": ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"],
        "snake": "#a371f7",
        "border": "#ffffff0d",
        "text": "#8b949e",
    },
}


# ---------------------------------------------------------------- data
def fetch_counts():
    sample = os.environ.get("SAMPLE_DATA")
    if sample:
        with open(sample) as f:
            return {k: int(v) for k, v in json.load(f).items()}

    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            weeks { contributionDays { date contributionCount } }
          }
        }
      }
    }"""
    body = json.dumps({
        "query": query,
        "variables": {
            "login": USER,
            "from": f"{YEAR}-01-01T00:00:00Z",
            "to": f"{YEAR}-12-31T23:59:59Z",
        },
    }).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={
            "Authorization": f"bearer {os.environ['GITHUB_TOKEN']}",
            "Content-Type": "application/json",
            "User-Agent": "profile-snake-generator",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    if "errors" in data:
        raise SystemExit(f"GraphQL error: {data['errors']}")
    weeks = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    return {d["date"]: d["contributionCount"] for w in weeks for d in w["contributionDays"]}


def build_grid(counts):
    """Return list of cells: dict(date, col, row, count, level) for the whole year."""
    start = dt.date(YEAR, 1, 1)
    end = dt.date(YEAR, 12, 31)
    offset = (start.weekday() + 1) % 7          # Sunday = row 0, like GitHub
    nonzero = sorted(c for c in counts.values() if c > 0)

    def level(c):
        if c <= 0 or not nonzero:
            return 0
        # quartile thresholds over the year's non-zero days, like GitHub
        q = [nonzero[int(len(nonzero) * p) - 1 if int(len(nonzero) * p) else 0] for p in (0.25, 0.5, 0.75)]
        if c <= q[0]:
            return 1
        if c <= q[1]:
            return 2
        if c <= q[2]:
            return 3
        return 4

    cells = []
    d = start
    while d <= end:
        idx = (d - start).days + offset
        c = counts.get(d.isoformat(), 0)
        cells.append({"date": d, "col": idx // 7, "row": idx % 7, "count": c, "level": level(c)})
        d += dt.timedelta(days=1)
    return cells


# ---------------------------------------------------------------- snake path
def plan_path(cells):
    """Greedy walk: always head to the nearest uneaten contribution cell."""
    targets = {(c["col"], c["row"]) for c in cells if c["level"] > 0}
    cols = max(c["col"] for c in cells) + 1
    pos = (-1, 0)                               # enter from the left edge
    path = [pos]
    eaten = {}

    def walk_to(goal):
        nonlocal pos
        while pos != goal:
            x, y = pos
            gx, gy = goal
            if x != gx:
                x += 1 if gx > x else -1
            else:
                y += 1 if gy > y else -1
            pos = (x, y)
            path.append(pos)
            if pos in targets and pos not in eaten:
                eaten[pos] = len(path) - 1

    while len(eaten) < len(targets):
        remaining = [t for t in targets if t not in eaten]
        goal = min(remaining, key=lambda t: (abs(t[0] - pos[0]) + abs(t[1] - pos[1]), t))
        walk_to(goal)

    if not targets:
        walk_to((cols // 2, 3))                 # nothing to eat: still crawl across
    walk_to((cols, pos[1]))                     # leave on the right edge
    for _ in range(SNAKE_LEN):                  # let the tail fully exit
        pos = (pos[0] + 1, pos[1])
        path.append(pos)
    return path, eaten, cols


# ---------------------------------------------------------------- svg: snake
def pct(i, n):
    return f"{i / n * 100:.3f}"


def snake_svg(cells, path, eaten, cols, theme):
    t = THEMES[theme]
    steps = len(path) - 1
    hold = 8                                    # pause steps at loop end
    total_steps = steps + hold
    dur = total_steps * STEP_SEC

    width = PAD_X * 2 + cols * STEP - GAP
    height = PAD_Y * 2 + 7 * STEP - GAP + 18

    def xy(p):
        return PAD_X + p[0] * STEP, PAD_Y + p[1] * STEP

    css = [
        f".c{{shape-rendering:geometricPrecision;rx:2;ry:2;stroke:{t['border']};stroke-width:1px}}",
        f".s{{fill:{t['snake']};animation:none {dur:.2f}s linear infinite}}",
    ]
    body = []

    # month labels above the grid
    start = dt.date(YEAR, 1, 1)
    offset = (start.weekday() + 1) % 7
    for m in range(1, 13):
        col = ((dt.date(YEAR, m, 1) - start).days + offset) // 7
        body.append(
            f'<text x="{PAD_X + col * STEP}" y="{PAD_Y - 10}" fill="{t['text']}" '
            f'font-size="10" font-family="Segoe UI,Helvetica,Arial,sans-serif">{dt.date(YEAR, m, 1):%b}</text>'
        )

    # cells
    for i, c in enumerate(cells):
        x, y = xy((c["col"], c["row"]))
        fill = t["levels"][c["level"]]
        key = (c["col"], c["row"])
        if key in eaten:
            p = float(pct(eaten[key], total_steps))
            css.append(
                f"@keyframes e{i}{{0%,{p:.3f}%{{fill:{fill}}}{p + 0.01:.3f}%,100%{{fill:{t['levels'][0]}}}}}"
                f".e{i}{{animation:e{i} {dur:.2f}s linear infinite}}"
            )
            body.append(f'<rect class="c e{i}" x="{x}" y="{y}" width="{CELL}" height="{CELL}" fill="{fill}"/>')
        else:
            body.append(f'<rect class="c" x="{x}" y="{y}" width="{CELL}" height="{CELL}" fill="{fill}"/>')

    # snake segments: segment k trails the head by k steps
    for k in range(SNAKE_LEN):
        frames = []
        last = None
        for i in range(total_steps + 1):
            p = path[max(0, min(i - k, steps))]
            if p == last and 0 < i < total_steps:
                continue
            x, y = xy(p)
            frames.append(f"{pct(i, total_steps)}%{{transform:translate({x}px,{y}px)}}")
            last = p
        css.append(f"@keyframes s{k}{{{''.join(frames)}}}.s{k}{{animation-name:s{k}}}")
        size = CELL - k * 1.2
        off = (CELL - size) / 2
        body.append(
            f'<rect class="s s{k}" x="{off:.1f}" y="{off:.1f}" width="{size:.1f}" height="{size:.1f}" rx="{size / 2.6:.1f}"/>'
        )

    # progress bar
    bar_y = height - PAD_Y + 4
    css.append(
        f"@keyframes pb{{0%{{width:0}}{pct(steps, total_steps)}%,100%{{width:{width - 2 * PAD_X}px}}}}"
        f".pb{{fill:{t['levels'][1]};animation:pb {dur:.2f}s linear infinite}}"
    )
    body.append(f'<rect class="pb" x="{PAD_X}" y="{bar_y}" height="4" rx="2" width="0"/>')

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">'
        f'<desc>Contribution snake for {USER}, {YEAR}</desc>'
        f"<style>{''.join(css)}</style>{''.join(body)}</svg>"
    )


# ---------------------------------------------------------------- svg: activity graph
def activity_svg(cells):
    today = dt.date.today()
    days = [c for c in cells if c["date"] <= today] or cells[:1]
    W, H = 1000, 320
    L, R, T, B = 50, 20, 50, 40
    pw, ph = W - L - R, H - T - B
    n = len(cells)                               # x axis spans the whole year
    ymax = max(4, max(c["count"] for c in days))
    ymax = ((ymax + 3) // 4) * 4                 # round to a multiple of 4 for even gridlines

    def px(i):
        return L + i / (n - 1) * pw

    def py(v):
        return T + ph - v / ymax * ph

    pts = [(px(i), py(c["count"])) for i, c in enumerate(days)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"{L},{T + ph} {line} {pts[-1][0]:.1f},{T + ph}"

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="Segoe UI,Helvetica,Arial,sans-serif">',
        '<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#1f6feb" stop-opacity=".45"/>'
        '<stop offset="1" stop-color="#1f6feb" stop-opacity="0"/></linearGradient></defs>',
        f'<rect width="{W}" height="{H}" rx="8" fill="#0d1117"/>',
        f'<text x="{W / 2}" y="30" fill="#58a6ff" font-size="17" font-weight="600" text-anchor="middle">'
        f"{USER}'s Contribution Graph · {YEAR}</text>",
    ]
    for g in range(5):
        v = ymax * g / 4
        y = py(v)
        out.append(f'<line x1="{L}" y1="{y:.1f}" x2="{W - R}" y2="{y:.1f}" stroke="#30363d" stroke-dasharray="3 4"/>')
        out.append(f'<text x="{L - 8}" y="{y + 4:.1f}" fill="#8b949e" font-size="11" text-anchor="end">{int(v)}</text>')
    for m in range(1, 13):
        i = (dt.date(YEAR, m, 1) - dt.date(YEAR, 1, 1)).days
        x = px(i)
        out.append(f'<text x="{x + 2:.1f}" y="{H - 16}" fill="#8b949e" font-size="11">{dt.date(YEAR, m, 1):%b}</text>')
    out.append(f'<polygon points="{area}" fill="url(#g)"/>')
    out.append(f'<polyline points="{line}" fill="none" stroke="#1f6feb" stroke-width="2" stroke-linejoin="round"/>')
    for (x, y), c in zip(pts, days):
        if c["count"] > 0:
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="#58a6ff"><title>{c["date"]}: {c["count"]}</title></circle>')
    total = sum(c["count"] for c in days)
    out.append(f'<text x="{W - R}" y="30" fill="#8b949e" font-size="12" text-anchor="end">{total} contributions</text>')
    out.append("</svg>")
    return "".join(out)


def main():
    counts = fetch_counts()
    cells = build_grid(counts)
    path, eaten, cols = plan_path(cells)
    os.makedirs(OUT, exist_ok=True)
    files = {
        "github-contribution-grid-snake.svg": snake_svg(cells, path, eaten, cols, "light"),
        "github-contribution-grid-snake-dark.svg": snake_svg(cells, path, eaten, cols, "dark"),
        "activity-graph.svg": activity_svg(cells),
    }
    for name, svg in files.items():
        with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
            f.write(svg)
    print(f"{USER} {YEAR}: {sum(counts.values())} contributions, {len(eaten)} cells eaten, {len(path)} steps")


if __name__ == "__main__":
    main()

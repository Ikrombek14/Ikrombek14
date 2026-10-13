#!/usr/bin/env python3
"""Generate profile SVGs from the same calendar shown on the GitHub profile.

Outputs (in OUT_DIR, default dist/):
  github-contribution-grid-snake.svg       snake animation, light theme
  github-contribution-grid-snake-dark.svg  snake animation, dark theme
  activity-graph.svg                       daily contribution line chart

Data comes from the public profile calendar (github.com/users/<login>/contributions),
so private contributions count exactly as they do on the profile. If that page
can't be read, the GraphQL API is used instead (public contributions only).

Env:
  GH_USER       GitHub login (default: repository owner)
  RANGE         "last-year" (default, same as the profile) or a year such as "2026"
  GITHUB_TOKEN  only needed for the GraphQL fallback
  SAMPLE_HTML   optional path to a saved contributions page, for local testing
"""
import datetime as dt
import html
import json
import os
import re
import urllib.request

USER = os.environ.get("GH_USER") or os.environ.get("GITHUB_REPOSITORY_OWNER", "Ikrombek14")
RANGE = (os.environ.get("RANGE") or "last-year").strip()
OUT = os.environ.get("OUT_DIR", "dist")

CELL, GAP = 12, 3
STEP = CELL + GAP
PAD_X, PAD_Y = 20, 34
STEP_SEC = 0.12          # time the snake needs per grid step
SNAKE_LEN = 5
FONT = "Segoe UI,Helvetica,Arial,sans-serif"
SOURCE = {}

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
def http_get(url, headers=None, data=None):
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": "Mozilla/5.0 (profile-snake-generator)", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def parse_profile_page(page):
    """Parse github.com/users/<login>/contributions -> ({date: (count, level)}, total)."""
    # tooltip text per cell id: "5 contributions on ...", "No contributions on ..."
    tips = {}
    for m in re.finditer(r'<tool-tip\b[^>]*\bfor="([^"]+)"[^>]*>(.*?)</tool-tip>', page, re.S):
        text = html.unescape(m.group(2)).strip()
        n = re.match(r"([\d,]+)\s+contribution", text)
        tips[m.group(1)] = int(n.group(1).replace(",", "")) if n else 0

    days = {}
    for m in re.finditer(r"<td\b[^>]*>", page):
        tag = m.group(0)
        date = re.search(r'data-date="(\d{4}-\d{2}-\d{2})"', tag)
        level = re.search(r'data-level="(\d)"', tag)
        if not (date and level):
            continue
        cid = re.search(r'\bid="([^"]+)"', tag)
        lvl = int(level.group(1))
        count = tips.get(cid.group(1)) if cid else None
        if count is None:
            count = lvl                      # no tooltip: the level is the best estimate
        days[date.group(1)] = (count, lvl)

    total = re.search(r"([\d,]+)\s+contributions?\s+in\s+(?:the last year|\d{4})", page)
    total = int(total.group(1).replace(",", "")) if total else sum(c for c, _ in days.values())
    return days, total


def fetch_profile():
    sample = os.environ.get("SAMPLE_HTML")
    if sample:
        with open(sample, encoding="utf-8") as f:
            return parse_profile_page(f.read())
    url = f"https://github.com/users/{USER}/contributions"
    if RANGE.isdigit():
        url += f"?from={RANGE}-01-01&to={RANGE}-12-31"
    return parse_profile_page(http_get(url))


def fetch_graphql(start, end):
    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            totalContributions
            weeks { contributionDays { date contributionCount contributionLevel } }
          }
        }
      }
    }"""
    body = json.dumps({"query": query, "variables": {
        "login": USER, "from": f"{start}T00:00:00Z", "to": f"{end}T23:59:59Z"}}).encode()
    data = json.loads(http_get("https://api.github.com/graphql", data=body, headers={
        "Authorization": f"bearer {os.environ['GITHUB_TOKEN']}",
        "Content-Type": "application/json"}))
    if "errors" in data:
        raise SystemExit(f"GraphQL error: {data['errors']}")
    cal = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    levels = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2,
              "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}
    days = {d["date"]: (d["contributionCount"], levels.get(d["contributionLevel"], 0))
            for w in cal["weeks"] for d in w["contributionDays"]}
    return days, cal["totalContributions"]


def load_data():
    try:
        days, total = fetch_profile()
        if days:
            print(f"source: profile page ({len(days)} days)")
            SOURCE["name"] = "profile-page"
            return days, total
        print("profile page had no calendar cells, falling back to GraphQL")
    except Exception as e:                    # noqa: BLE001 - any failure -> fallback
        print(f"profile page unavailable ({e}), falling back to GraphQL")
        SOURCE["error"] = str(e)
    if RANGE.isdigit():
        start, end = f"{RANGE}-01-01", f"{RANGE}-12-31"
    else:
        today = dt.date.today()
        start, end = (today - dt.timedelta(days=365)).isoformat(), today.isoformat()
    SOURCE["name"] = "graphql"
    return fetch_graphql(start, end)


def build_grid(days):
    """Lay the days out GitHub-style: one column per week, Sunday on top."""
    if RANGE.isdigit():
        start, end = dt.date(int(RANGE), 1, 1), dt.date(int(RANGE), 12, 31)
    else:
        dates = sorted(dt.date.fromisoformat(d) for d in days)
        start, end = dates[0], dates[-1]
    offset = (start.weekday() + 1) % 7
    cells = []
    d = start
    while d <= end:
        idx = (d - start).days + offset
        count, level = days.get(d.isoformat(), (0, 0))
        cells.append({"date": d, "col": idx // 7, "row": idx % 7, "count": count, "level": level})
        d += dt.timedelta(days=1)
    return cells


def month_labels(cells):
    """(col, label) at the first column where each month starts, like the profile."""
    labels = []
    for c in cells:
        first = c["date"].day == 1
        lead = c is cells[0] and c["date"].day <= 14
        if not (first or lead):
            continue
        col = c["col"] + (1 if first and c["row"] > 0 else 0)
        if labels and col - labels[-1][0] < 3:
            continue
        labels.append((col, f"{c['date']:%b}"))
    return labels


def range_label(cells):
    return RANGE if RANGE.isdigit() else "last year"


# ---------------------------------------------------------------- snake path
def plan_path(cells):
    """Greedy walk: always head to the nearest uneaten contribution cell."""
    valid = {(c["col"], c["row"]) for c in cells}
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
    assert all(p in valid for p in eaten)
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

    for col, label in month_labels(cells):
        body.append(f'<text x="{PAD_X + col * STEP}" y="{PAD_Y - 10}" fill="{t["text"]}" '
                    f'font-size="10" font-family="{FONT}">{label}</text>')

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

    bar_y = height - PAD_Y + 4
    css.append(
        f"@keyframes pb{{0%{{width:0}}{pct(steps, total_steps)}%,100%{{width:{width - 2 * PAD_X}px}}}}"
        f".pb{{fill:{t['levels'][1]};animation:pb {dur:.2f}s linear infinite}}"
    )
    body.append(f'<rect class="pb" x="{PAD_X}" y="{bar_y}" height="4" rx="2" width="0"/>')

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">'
        f"<desc>Contribution snake for {USER}, {range_label(cells)}</desc>"
        f"<style>{''.join(css)}</style>{''.join(body)}</svg>"
    )


# ---------------------------------------------------------------- svg: activity graph
def activity_svg(cells, total):
    today = dt.date.today()
    days = [c for c in cells if c["date"] <= today] or cells[:1]
    W, H = 1000, 320
    L, R, T, B = 50, 20, 50, 40
    pw, ph = W - L - R, H - T - B
    n = len(cells)
    ymax = max(4, max(c["count"] for c in days))
    ymax = ((ymax + 3) // 4) * 4

    def px(i):
        return L + i / max(1, n - 1) * pw

    def py(v):
        return T + ph - v / ymax * ph

    pts = [(px(i), py(c["count"])) for i, c in enumerate(days)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"{L},{T + ph} {line} {pts[-1][0]:.1f},{T + ph}"
    title = f"{USER}'s Contribution Graph · {range_label(cells)}"

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="{FONT}">',
        '<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#1f6feb" stop-opacity=".45"/>'
        '<stop offset="1" stop-color="#1f6feb" stop-opacity="0"/></linearGradient></defs>',
        f'<rect width="{W}" height="{H}" rx="8" fill="#0d1117"/>',
        f'<text x="{W / 2}" y="30" fill="#58a6ff" font-size="17" font-weight="600" text-anchor="middle">{title}</text>',
        f'<text x="{W - R}" y="30" fill="#8b949e" font-size="12" text-anchor="end">{total} contributions</text>',
    ]
    for g in range(5):
        v = ymax * g / 4
        y = py(v)
        out.append(f'<line x1="{L}" y1="{y:.1f}" x2="{W - R}" y2="{y:.1f}" stroke="#30363d" stroke-dasharray="3 4"/>')
        out.append(f'<text x="{L - 8}" y="{y + 4:.1f}" fill="#8b949e" font-size="11" text-anchor="end">{int(v)}</text>')
    for i, c in enumerate(cells):
        if c["date"].day == 1:
            out.append(f'<text x="{px(i) + 2:.1f}" y="{H - 16}" fill="#8b949e" font-size="11">{c["date"]:%b}</text>')
    out.append(f'<polygon points="{area}" fill="url(#g)"/>')
    out.append(f'<polyline points="{line}" fill="none" stroke="#1f6feb" stroke-width="2" stroke-linejoin="round"/>')
    for (x, y), c in zip(pts, days):
        if c["count"] > 0:
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="#58a6ff"><title>{c["date"]}: {c["count"]}</title></circle>')
    out.append("</svg>")
    return "".join(out)


def main():
    days, total = load_data()
    cells = build_grid(days)
    path, eaten, cols = plan_path(cells)
    os.makedirs(OUT, exist_ok=True)
    files = {
        "github-contribution-grid-snake.svg": snake_svg(cells, path, eaten, cols, "light"),
        "github-contribution-grid-snake-dark.svg": snake_svg(cells, path, eaten, cols, "dark"),
        "activity-graph.svg": activity_svg(cells, total),
    }
    for name, svg in files.items():
        with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
            f.write(svg)
    files["meta.json"] = json.dumps({**SOURCE, "total": total, "eaten": len(eaten),
                                     "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})
    for name in ("meta.json",):
        with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
            f.write(files[name])
    print(f"{USER} ({range_label(cells)}): {total} contributions, "
          f"{len(eaten)} cells eaten, {len(path)} steps, {cols} weeks")


if __name__ == "__main__":
    main()

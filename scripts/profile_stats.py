"""Render the GitHub stats and top-languages cards shown in README.md.

Runs in the "Generate profile images" workflow so the README does not depend on
a third-party card service. Standard library only.

    GITHUB_TOKEN=... python scripts/profile_stats.py <user> <out_dir>

Writes stats-dark.svg, stats-light.svg, langs-dark.svg and langs-light.svg.
"""

import json
import os
import sys
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

QUERY = """
query($login: String!) {
  user(login: $login) {
    pullRequests { totalCount }
    merged: pullRequests(states: MERGED) { totalCount }
    issues { totalCount }
    contributionsCollection { totalCommitContributions restrictedContributionsCount }
    repositoriesContributedTo(contributionTypes: [COMMIT, PULL_REQUEST, ISSUE, REPOSITORY]) { totalCount }
    repositories(ownerAffiliations: OWNER, isFork: false, first: 100) {
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""

# Notebook outputs inflate byte counts, so they would drown out real code.
EXCLUDED_LANGUAGES = {"Jupyter Notebook"}
TOP_LANGUAGES = 6

THEMES = {
    "dark": {"bg": "#0d1117", "border": "#30363d", "title": "#36bcf7", "text": "#c9d1d9",
             "muted": "#8b949e", "icon": "#36bcf7", "track": "#21262d"},
    "light": {"bg": "#ffffff", "border": "#d0d7de", "title": "#0e75b6", "text": "#1f2328",
              "muted": "#59636e", "icon": "#0e75b6", "track": "#eaeef2"},
}

# 16px Octicons paths (MIT), drawn in the theme's icon colour.
ICONS = {
    "star": "M8 .25a.75.75 0 0 1 .673.418l1.882 3.815 4.21.612a.75.75 0 0 1 .416 1.279l-3.046 2.97.719 4.192a.751.751 0 0 1-1.088.791L8 12.347l-3.766 1.98a.75.75 0 0 1-1.088-.79l.72-4.194L.818 6.374a.75.75 0 0 1 .416-1.28l4.21-.611L7.327.668A.75.75 0 0 1 8 .25Z",
    "commit": "M11.93 8.5a4.002 4.002 0 0 1-7.86 0H.75a.75.75 0 0 1 0-1.5h3.32a4.002 4.002 0 0 1 7.86 0h3.32a.75.75 0 0 1 0 1.5Zm-1.43-.75a2.5 2.5 0 1 0-5 0 2.5 2.5 0 0 0 5 0Z",
    "pr": "M1.5 3.25a2.25 2.25 0 1 1 3 2.122v5.256a2.251 2.251 0 1 1-1.5 0V5.372A2.25 2.25 0 0 1 1.5 3.25Zm5.677-.177L9.573.677A.25.25 0 0 1 10 .854V2.5h1A2.5 2.5 0 0 1 13.5 5v5.628a2.251 2.251 0 1 1-1.5 0V5a1 1 0 0 0-1-1h-1v1.646a.25.25 0 0 1-.427.177L7.177 3.427a.25.25 0 0 1 0-.354ZM3.75 2.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm0 9.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm8.25.75a.75.75 0 1 0 1.5 0 .75.75 0 0 0-1.5 0Z",
    "merged": "M5.45 5.154A4.25 4.25 0 0 0 9.25 7.5h1.378a2.251 2.251 0 1 1 0 1.5H9.25A5.734 5.734 0 0 1 5 7.123v3.505a2.25 2.25 0 1 1-1.5 0V5.372a2.25 2.25 0 1 1 1.95-.218ZM4.25 13.5a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Zm8.5-4.5a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5ZM5 3.25a.75.75 0 1 0 0 .005V3.25Z",
    "issue": "M8 9.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0ZM1.5 8a6.5 6.5 0 1 0 13 0 6.5 6.5 0 0 0-13 0Z",
    "repo": "M2 2.5A2.5 2.5 0 0 1 4.5 0h8.75a.75.75 0 0 1 .75.75v12.5a.75.75 0 0 1-.75.75h-2.5a.75.75 0 0 1 0-1.5h1.75v-2h-8a1 1 0 0 0-.714 1.7.75.75 0 1 1-1.072 1.05A2.495 2.495 0 0 1 2 11.5Zm10.5-1h-8a1 1 0 0 0-1 1v6.708A2.486 2.486 0 0 1 4.5 9h8ZM5 12.25a.25.25 0 0 1 .25-.25h3.5a.25.25 0 0 1 .25.25v3.25a.25.25 0 0 1-.4.2l-1.45-1.087a.249.249 0 0 0-.3 0L5.4 15.7a.25.25 0 0 1-.4-.2Z",
}

FONT = "font-family=\"'Segoe UI', Ubuntu, 'Helvetica Neue', sans-serif\""
WIDTH, HEIGHT = 420, 195


def fetch(login, token):
    body = json.dumps({"query": QUERY, "variables": {"login": login}}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if payload.get("errors"):
        raise SystemExit(f"GraphQL error: {payload['errors']}")
    return payload["data"]["user"]


def summarize(user):
    repos = user["repositories"]["nodes"]
    contributions = user["contributionsCollection"]
    stats = [
        ("star", "Stars earned", sum(r["stargazerCount"] for r in repos)),
        ("commit", "Commits (last year)",
         contributions["totalCommitContributions"] + contributions["restrictedContributionsCount"]),
        ("pr", "Pull requests", user["pullRequests"]["totalCount"]),
        ("merged", "Merged pull requests", user["merged"]["totalCount"]),
        ("issue", "Issues", user["issues"]["totalCount"]),
        ("repo", "Contributed to", user["repositoriesContributedTo"]["totalCount"]),
    ]

    sizes, colors = {}, {}
    for repo in repos:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            if name in EXCLUDED_LANGUAGES:
                continue
            sizes[name] = sizes.get(name, 0) + edge["size"]
            colors[name] = edge["node"]["color"] or "#8b949e"
    total = sum(sizes.values()) or 1
    top = sorted(sizes.items(), key=lambda item: item[1], reverse=True)[:TOP_LANGUAGES]
    languages = [(name, colors[name], size / total * 100) for name, size in top]
    return stats, languages


def fmt(n):
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def frame(theme, title, inner, label):
    t = THEMES[theme]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label="{escape(label)}">\n'
        f"<title>{escape(label)}</title>\n"
        f'<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{HEIGHT - 1}" rx="6" '
        f'fill="{t["bg"]}" stroke="{t["border"]}"/>\n'
        f'<text x="25" y="35" {FONT} font-size="18" font-weight="600" fill="{t["title"]}">{escape(title)}</text>\n'
        f"{inner}</svg>\n"
    )


def stats_card(stats, theme):
    t = THEMES[theme]
    rows = []
    for i, (icon, label, value) in enumerate(stats):
        y = 62 + i * 23
        rows.append(
            f'<g transform="translate(25 {y})">'
            f'<path transform="translate(0 -12)" fill="{t["icon"]}" d="{ICONS[icon]}"/>'
            f'<text x="26" {FONT} font-size="14" fill="{t["text"]}">{escape(label)}:</text>'
            f'<text x="{WIDTH - 50}" text-anchor="end" {FONT} font-size="14" font-weight="700" '
            f'fill="{t["text"]}">{fmt(value)}</text></g>\n'
        )
    label = "GitHub stats: " + ", ".join(f"{name} {value}" for _, name, value in stats)
    return frame(theme, "GitHub Stats", "".join(rows), label)


def langs_card(languages, theme):
    t = THEMES[theme]
    bar_x, bar_w = 25, WIDTH - 50
    parts = [f'<clipPath id="bar"><rect x="{bar_x}" y="55" width="{bar_w}" height="8" rx="4"/></clipPath>\n'
             f'<g clip-path="url(#bar)"><rect x="{bar_x}" y="55" width="{bar_w}" height="8" fill="{t["track"]}"/>']
    x = bar_x
    for _, color, pct in languages:
        w = bar_w * pct / 100
        parts.append(f'<rect x="{x:.2f}" y="55" width="{w:.2f}" height="8" fill="{color}"/>')
        x += w
    parts.append("</g>\n")

    for i, (name, color, pct) in enumerate(languages):
        col, row = i % 2, i // 2
        cx, cy = 30 + col * 190, 95 + row * 30
        parts.append(
            f'<circle cx="{cx}" cy="{cy - 5}" r="5" fill="{color}"/>'
            f'<text x="{cx + 12}" y="{cy}" {FONT} font-size="13" fill="{t["text"]}">{escape(name)} '
            f'<tspan fill="{t["muted"]}">{pct:.1f}%</tspan></text>\n'
        )
    label = "Most used languages: " + ", ".join(f"{name} {pct:.1f}%" for name, _, pct in languages)
    return frame(theme, "Most Used Languages", "".join(parts), label)


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    login, out_dir = sys.argv[1], Path(sys.argv[2])
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is not set")

    stats, languages = summarize(fetch(login, token))
    out_dir.mkdir(parents=True, exist_ok=True)
    for theme in THEMES:
        (out_dir / f"stats-{theme}.svg").write_text(stats_card(stats, theme), encoding="utf-8")
        (out_dir / f"langs-{theme}.svg").write_text(langs_card(languages, theme), encoding="utf-8")


if __name__ == "__main__":
    main()

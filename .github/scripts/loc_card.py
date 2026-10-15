#!/usr/bin/env python3
"""Draw an SVG card with the total lines of code a GitHub user has committed.

Uses GitHub's /repos/{owner}/{repo}/stats/contributors endpoint, which reports
weekly additions and deletions per author, and counts only GH_USER's own lines.

Environment:
  GH_TOKEN       token used for the API (classic PAT; add `repo` scope to count private repos)
  GH_USER        whose lines to count (defaults to the repository owner)
  OUTPUT         where to write the SVG              (default: loc.svg)
  CACHE          per-repo totals from the last run   (default: .github/loc-stats.json)
  SKIP_REPOS     comma-separated repo names to leave out
  INCLUDE_FORKS  "true" to also count your commits in forks (default: false)
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

API = "https://api.github.com"
MAX_ROUNDS = 12      # GitHub computes stats lazily and answers 202 until they're ready
ROUND_DELAY = 10     # seconds between retry rounds


def env(name, default=""):
    return os.environ.get(name, default).strip()


def request(path, token):
    req = urllib.request.Request(API + path, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "loc-card",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
            return resp.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as err:
        return err.code, None
    except (urllib.error.URLError, TimeoutError) as err:
        print(f"  network error on {path}: {err}")
        return 0, None


def list_repos(token, skip, include_forks):
    repos, page = [], 1
    while True:
        status, data = request(
            f"/user/repos?affiliation=owner,collaborator,organization_member&per_page=100&page={page}", token)
        if status != 200:
            sys.exit(f"Could not list repositories (HTTP {status}). Check that METRICS_TOKEN is set and valid.")
        repos += data
        if len(data) < 100:
            break
        page += 1
    keep = []
    for r in repos:
        if r.get("fork") and not include_forks:
            continue
        if r["name"].lower() in skip or r["full_name"].lower() in skip:
            continue
        keep.append(r["full_name"])
    return sorted(set(keep))


def user_totals(stats, user):
    for contributor in stats or []:
        login = (contributor.get("author") or {}).get("login") or ""
        if login.lower() == user.lower():
            weeks = contributor.get("weeks") or []
            return {
                "added": sum(w.get("a", 0) for w in weeks),
                "deleted": sum(w.get("d", 0) for w in weeks),
                "commits": contributor.get("total", 0),
            }
    return {"added": 0, "deleted": 0, "commits": 0}


def collect(repos, token, user):
    """Return ({repo: totals}, [repos GitHub never answered for])."""
    results, pending = {}, list(repos)
    for attempt in range(1, MAX_ROUNDS + 1):
        waiting = []
        for full in pending:
            status, data = request(f"/repos/{full}/stats/contributors", token)
            if status == 200 and isinstance(data, list):
                results[full] = user_totals(data, user)
            elif status == 202:
                waiting.append(full)
            elif status == 204:                      # empty repository
                results[full] = {"added": 0, "deleted": 0, "commits": 0}
            else:
                print(f"  {full}: HTTP {status}, skipping this run")
        pending = waiting
        if not pending:
            break
        if attempt < MAX_ROUNDS:
            print(f"  {len(pending)} repo(s) still being computed by GitHub, retrying in {ROUND_DELAY}s")
            time.sleep(ROUND_DELAY)
    return results, pending


def compact(n):
    for size, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if abs(n) >= size:
            value = n / size
            text = f"{value:.0f}" if abs(value) >= 100 else f"{value:.1f}".rstrip("0").rstrip(".")
            return text + suffix
    return str(n)


def render(totals, updated):
    # Colours match github-readme-stats' "tokyonight" theme used elsewhere in the README
    bg, title, text, icon = "#1a1b27", "#70a5fd", "#38bdae", "#bf91f3"
    green, red = "#3fb950", "#f85149"
    rows = [
        ("Lines added", f"+{totals['added']:,}", green),
        ("Lines removed", f"−{totals['deleted']:,}", red),
        ("Net lines", f"{totals['added'] - totals['deleted']:,}", text),
        ("Commits", f"{totals['commits']:,}", text),
        ("Repositories", f"{totals['repos']:,}", text),
    ]
    row_svg = "\n".join(
        f'''    <g transform="translate(25, {68 + i * 25})">
      <circle cx="6" cy="-5" r="4" fill="{colour if colour != text else icon}"/>
      <text x="20" class="label">{label}:</text>
      <text x="150" class="value" fill="{colour}">{value}</text>
    </g>'''
        for i, (label, value, colour) in enumerate(rows)
    )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="495" height="195" viewBox="0 0 495 195" role="img" aria-labelledby="t">
  <title id="t">Lines of code committed: {totals['added']:,} added, {totals['deleted']:,} removed</title>
  <style>
    .title {{ font: 600 18px 'Segoe UI', Ubuntu, Sans-Serif; fill: {title}; }}
    .label {{ font: 600 14px 'Segoe UI', Ubuntu, Sans-Serif; fill: {text}; }}
    .value {{ font: 700 14px 'Segoe UI', Ubuntu, Sans-Serif; }}
    .big   {{ font: 800 28px 'Segoe UI', Ubuntu, Sans-Serif; fill: {title}; }}
    .cap   {{ font: 600 12px 'Segoe UI', Ubuntu, Sans-Serif; fill: {text}; }}
    .foot  {{ font: 400 10px 'Segoe UI', Ubuntu, Sans-Serif; fill: {text}; opacity: .6; }}
  </style>
  <rect x="0.5" y="0.5" rx="4.5" width="494" height="194" fill="{bg}" stroke="#e4e2e2" stroke-opacity="0"/>
  <text x="25" y="35" class="title">Lines of Code Committed</text>
{row_svg}
  <g transform="translate(395, 100)">
    <circle r="52" fill="none" stroke="{icon}" stroke-opacity=".8" stroke-width="5"/>
    <text y="4" text-anchor="middle" class="big">{compact(totals['added'])}</text>
    <text y="24" text-anchor="middle" class="cap">lines written</text>
  </g>
  <text x="470" y="182" text-anchor="end" class="foot">updated {updated}</text>
</svg>
'''


def main():
    token = env("GH_TOKEN")
    if not token:
        sys.exit("GH_TOKEN is empty. Add a METRICS_TOKEN secret to this repository.")
    user = env("GH_USER") or env("GITHUB_REPOSITORY_OWNER")
    output = env("OUTPUT", "loc.svg")
    cache_path = env("CACHE", ".github/loc-stats.json")
    skip = {s.strip().lower() for s in env("SKIP_REPOS").split(",") if s.strip()}
    include_forks = env("INCLUDE_FORKS", "false").lower() == "true"

    repos = list_repos(token, skip, include_forks)
    print(f"Counting {user}'s lines across {len(repos)} repositories")

    try:
        with open(cache_path) as f:
            cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cache = {}

    results, missing = collect(repos, token, user)

    # Repos GitHub didn't answer for this time keep last run's numbers, so the card never dips
    per_repo = {}
    for full in repos:
        if full in results:
            per_repo[full] = results[full]
        elif full in cache:
            per_repo[full] = cache[full]
            print(f"  {full}: using cached numbers")
        elif full in missing:
            print(f"  {full}: no data yet, will be counted on a later run")

    totals = {
        "added": sum(r["added"] for r in per_repo.values()),
        "deleted": sum(r["deleted"] for r in per_repo.values()),
        "commits": sum(r["commits"] for r in per_repo.values()),
        "repos": sum(1 for r in per_repo.values() if r["commits"] or r["added"] or r["deleted"]),
    }
    for full, r in sorted(per_repo.items(), key=lambda kv: -kv[1]["added"]):
        if r["added"] or r["deleted"]:
            print(f"  {full}: +{r['added']:,} -{r['deleted']:,} ({r['commits']} commits)")
    print(f"Total: +{totals['added']:,} -{totals['deleted']:,} across {totals['repos']} repos")

    updated = datetime.now(timezone.utc).strftime("%d %b %Y")
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    with open(output, "w") as f:
        f.write(render(totals, updated))
    os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(per_repo, f, indent=2, sort_keys=True)
        f.write("\n")


if __name__ == "__main__":
    main()

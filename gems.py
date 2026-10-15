#!/usr/bin/env python3
"""session-gems clusterer: group a digest into themes (built, fixed, tools, pain points, numbers)
and optionally pull recent X posts for trend hooks.

  python3 gems.py out/digest-2026-01-01.json > themes.json
  X_BEARER_TOKEN=... python3 gems.py digest.json --x-query "MCP agents" --x-query "Next.js"

The X step is skipped unless X_BEARER_TOKEN is set. Standard library only.
"""
import argparse, collections, json, os, re, sys, urllib.parse, urllib.request

THEMES = {
    "built": r"\b(feat|add|build|launch|new|ship|create)",
    "fixed": r"\b(fix|bug|resolve|repair|patch|hotfix)",
    "tools": r"\b(mcp|agent|claude|grok|codex|cursor|vercel|next\.?js|expo|react native|lint|cloudflare|docker|proxy)",
    "pain": r"(limit|fail|error|broken|blank|too long|rate limit|blocked|timeout|flaky)",
}
NUM = re.compile(r"[$+]?\d[\d,.]*\s?(%|k|M|ms|s|tests|leads|keywords|fixes|PRs|users|files)\b")


def cluster(d, per_theme=200):
    commits = {}
    for g in d.get("git", []):
        commits.setdefault((g["subject"], g["date"][:10]), g)  # collapse cherry-picks / rebases
    out = {"commits_unique": len(commits),
           "by_repo": collections.Counter(c["repo"].rstrip("/").split("/")[-1] for c in commits.values()).most_common(30),
           "themes": {k: [] for k in THEMES}, "numbers": []}
    for c in commits.values():
        for k, rx in THEMES.items():
            if re.search(rx, c["subject"], re.I):
                out["themes"][k].append(f"{c['date'][:10]} {c['repo']}: {c['subject']}")
    for s in d.get("claude", []) + d.get("grok", []):
        src = f"{s['source']} {s.get('project')} {(s.get('end') or '')[:10]}"
        for m in s["assistant"] + s["prompts"]:
            for k, rx in THEMES.items():
                if re.search(rx, m["text"], re.I):
                    out["themes"][k].append(f"{src}: {m['text'][:240]}")
            for n in NUM.finditer(m["text"]):
                out["numbers"].append(f"{src}: ...{m['text'][max(0, n.start() - 80):n.end() + 40]}")
    for k in out["themes"]:
        out["themes"][k] = out["themes"][k][:per_theme]
    out["numbers"] = out["numbers"][:per_theme]
    return out


def x_search(query, token, n=10):
    url = "https://api.x.com/2/tweets/search/recent?" + urllib.parse.urlencode(
        {"query": f"{query} -is:retweet lang:en", "max_results": max(10, min(n, 100)), "tweet.fields": "created_at,public_metrics"})
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r).get("data", [])
    return [{"url": f"https://x.com/i/status/{p['id']}", "created_at": p.get("created_at"), "text": p["text"][:280],
             "likes": p.get("public_metrics", {}).get("like_count")} for p in data]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("digest")
    ap.add_argument("--x-query", action="append", default=[], help="repeatable; needs X_BEARER_TOKEN")
    a = ap.parse_args(argv)
    with open(a.digest) as fh:
        out = cluster(json.load(fh))
    token = os.environ.get("X_BEARER_TOKEN")
    if a.x_query and token:
        out["x"] = {}
        for q in a.x_query:
            try:
                out["x"][q] = x_search(q, token)
            except Exception as e:  # network or quota: keep going without trends
                out["x"][q] = {"error": str(e)[:200]}
    elif a.x_query:
        print("X_BEARER_TOKEN not set; skipping X step", file=sys.stderr)
    json.dump(out, sys.stdout, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()

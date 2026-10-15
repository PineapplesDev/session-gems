#!/usr/bin/env python3
"""session-gems collector: turn recent git commits and AI coding-agent sessions
(Claude Code, Grok build) into one compact, redacted JSON digest.

Standard library only. Runs locally. Never reads auth or credential files.
"""
import argparse, datetime as dt, json, os, re, subprocess, sys, time

HOME = os.path.expanduser("~")
SKIP_DIRS = {"Library", "node_modules", "Applications", "Pictures", "Music", "Movies", "venv", ".venv", "dist", "build"}

# Hard rule: any file whose name matches this is never opened.
NEVER_READ = re.compile(r"(auth|token|credential|secret|password|cookie|keychain|\.env|\.pem$|\.key$|id_rsa|id_ed25519)", re.I)

REDACTIONS = [
    (re.compile(r"-----BEGIN[^-]*PRIVATE KEY-----.*?-----END[^-]*-----", re.S), "[KEY]"),
    (re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{5,}"), "[JWT]"),
    (re.compile(r"\b(sk|pk|rk|xai|ghp|gho|ghs|ghu|github_pat|glpat|xox[abpr]|AKIA|AIza|ya29|sk-ant|sk-proj|whsec|shpat|SG)[-_.][A-Za-z0-9_\-.]{12,}"), "[TOKEN]"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}"), r"\1 [TOKEN]"),
    (re.compile(r"(?im)^\s*(export\s+)?[A-Z][A-Z0-9_]{2,}\s*=\s*\S+.*$"), "[ENV_LINE]"),
    (re.compile(r"(?i)\b(pass(word|wd)?|secret|token|api[_-]?key|auth|credential|cookie|session[_-]?id)(\"?\s*[:=]\s*)[\"']?[^\s\"',}]{4,}"), r"\1\3[REDACTED]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    (re.compile(r"(?i)\b(postgres(ql)?|mysql|mongodb(\+srv)?|redis|amqp)://\S+"), "[DB_URL]"),
    (re.compile(r"https?://[^\s/:@]+:[^\s@/]+@\S+"), "[URL_WITH_CREDS]"),
    (re.compile(r"\b[0-9a-fA-F]{32,}\b"), "[HEX]"),
    # No "/" in the class, so file paths survive; long opaque blobs do not.
    (re.compile(r"(?<![\w/.-])[A-Za-z0-9+_-]{40,}={0,2}(?![\w/])"), "[B64]"),
    (re.compile(r"\b\d{3}[-. ]\d{3}[-. ]\d{4}\b"), "[PHONE]"),
]
NOISE = re.compile(r"^(<command-|<local-command|<system-reminder|Caveat:|\[Request interrupted|<task-notification|This session is being continued)")


def redact(s, cap=None):
    if not isinstance(s, str):
        s = json.dumps(s)[:5000]
    if cap:
        s = s[: cap * 3]
    s = s.replace(HOME, "~")
    for rx, rep in REDACTIONS:
        s = rx.sub(rep, s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:cap] if cap else s


def safe_open(path):
    if NEVER_READ.search(os.path.basename(path)):
        raise PermissionError(f"refusing to read {path}")
    return open(path, errors="ignore")


def short(p):
    return p.replace(HOME, "~") if p else p


# ---------- git ----------
def find_repos(roots, maxdepth):
    out = []
    def walk(d, depth):
        try:
            ents = list(os.scandir(d))
        except OSError:
            return
        g = [e for e in ents if e.name == ".git"]
        if g:
            if g[0].is_dir():  # skip linked worktrees (.git is a file); their commits duplicate the main repo
                out.append(d)
            return
        if depth >= maxdepth:
            return
        for e in ents:
            if e.is_dir(follow_symlinks=False) and not e.name.startswith(".") and e.name not in SKIP_DIRS:
                walk(e.path, depth + 1)
    for r in roots:
        walk(os.path.expanduser(r), 0)
    return out


def collect_git(repos, days, max_commits):
    seen, res = set(), []
    for r in repos:
        try:
            o = subprocess.run(["git", "-C", r, "log", "--all", f"--since={days} days ago", "--no-merges", "--shortstat",
                                "--date=iso-strict", "--pretty=format:@@%H|%ad|%s"], capture_output=True, text=True, timeout=60).stdout
        except Exception:
            continue
        cur = None
        for line in o.splitlines():
            if line.startswith("@@"):
                h, d, s = (line[2:].split("|", 2) + ["", "", ""])[:3]
                if h in seen:  # same commit reachable from clones / forks
                    cur = None
                    continue
                seen.add(h)
                cur = {"repo": short(r), "hash": h[:10], "date": d, "subject": redact(s, 200)}
                res.append(cur)
            elif cur is not None and "changed" in line:
                cur["stats"] = line.strip()
    res.sort(key=lambda c: c["date"], reverse=True)
    return res[:max_commits]


# ---------- sessions ----------
def texts(c):
    if isinstance(c, str):
        return [c]
    out = []
    if isinstance(c, list):
        for b in c:
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str):
                out.append(b["text"])
            elif isinstance(b, str):
                out.append(b)
    elif isinstance(c, dict):
        for k in ("text", "content"):
            if k in c:
                out += texts(c[k])
    return out


class Session(dict):
    def add(self, role, txt, ts, cap_user, cap_asst):
        txt = (txt or "").strip()
        if not txt or NOISE.match(txt):
            return
        key, cap = ("prompts", cap_user) if role == "user" else ("assistant", cap_asst)
        self[key].append({"ts": ts, "text": redact(txt, cap)})

    def done(self, maxp, maxa):
        p, a = self["prompts"], self["assistant"]
        self["n_prompts"], self["n_assistant"] = len(p), len(a)
        self["prompts"] = p if len(p) <= maxp else p[: maxp - 5] + p[-5:]
        self["assistant"] = a[-maxa:]
        return dict(self)


def new_session(**kw):
    s = Session(prompts=[], assistant=[])
    s.update(kw)
    return s


def collect_claude(base, cutoff, a):
    out = []
    cut_iso = dt.datetime.fromtimestamp(cutoff, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    for root, _, files in os.walk(base):
        for f in files:
            fp = os.path.join(root, f)
            if not f.endswith(".jsonl") or os.path.getmtime(fp) < cutoff:
                continue
            s = new_session(source="claude", file=short(fp), project=None, start=None, end=None)
            try:
                with safe_open(fp) as fh:
                    for line in fh:
                        try:
                            j = json.loads(line)
                        except ValueError:
                            continue
                        t, ts = j.get("type"), j.get("timestamp")
                        if t not in ("user", "assistant") or j.get("isSidechain") or j.get("isMeta"):
                            continue
                        if ts:
                            s["start"] = s["start"] or ts
                            s["end"] = ts
                        s["project"] = s["project"] or short(j.get("cwd"))
                        if ts and ts < cut_iso:
                            continue
                        for x in texts((j.get("message") or {}).get("content")):
                            s.add(t, x, ts, a.cap_user, a.cap_assistant)
            except (OSError, PermissionError):
                continue
            if s["prompts"]:
                out.append(s.done(a.max_prompts, a.max_assistant))
    return out


def collect_grok(base, cutoff, a):
    """Grok build: <base>/<url-encoded cwd>/<session id>/{chat_history.jsonl, summary.json}. Only these two files are read."""
    out = []
    if not os.path.isdir(base):
        return out
    for proj in os.listdir(base):
        pd = os.path.join(base, proj)
        if not os.path.isdir(pd):
            continue
        for sid in os.listdir(pd):
            sd = os.path.join(pd, sid)
            ch = os.path.join(sd, "chat_history.jsonl")
            if not os.path.isfile(ch) or os.path.getmtime(ch) < cutoff:
                continue
            s = new_session(source="grok", project=short(proj.replace("%2F", "/")), session=sid, start=None, end=None)
            try:
                with safe_open(os.path.join(sd, "summary.json")) as fh:
                    sm = json.load(fh)
                s.update(title=redact(sm.get("session_summary", ""), 200), start=sm.get("created_at"), end=sm.get("updated_at"),
                         project=short(sm.get("info", {}).get("cwd")) or s["project"])
            except (OSError, ValueError, PermissionError):
                pass
            try:
                with safe_open(ch) as fh:
                    for line in fh:
                        try:
                            j = json.loads(line)
                        except ValueError:
                            continue
                        role = j.get("type") or j.get("role")
                        if role not in ("user", "assistant"):
                            continue
                        for x in texts(j.get("content") if "content" in j else j.get("message")):
                            m = re.search(r"<user_query>(.*?)</user_query>", x, re.S)
                            if role == "user" and m:
                                x = m.group(1)
                            elif role == "user" and len(x) > 4000:
                                continue  # injected context, not a human prompt
                            s.add(role, x, j.get("timestamp") or j.get("ts"), a.cap_user, a.cap_assistant)
            except (OSError, PermissionError):
                continue
            if s["prompts"]:
                out.append(s.done(a.max_prompts, a.max_assistant))
    return out


def main(argv=None):
    env = os.environ.get
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=int(env("GEMS_DAYS", 7)))
    ap.add_argument("--roots", default=env("GEMS_ROOTS", "~"), help="comma-separated dirs to search for git repos")
    ap.add_argument("--maxdepth", type=int, default=4)
    ap.add_argument("--sources", default=env("GEMS_SOURCES", "git,claude,grok"))
    ap.add_argument("--claude-dir", default=env("GEMS_CLAUDE_DIR", "~/.claude/projects"))
    ap.add_argument("--grok-dir", default=env("GEMS_GROK_DIR", "~/.grok/sessions"))
    ap.add_argument("--out", default=env("GEMS_OUT", "./out"))
    ap.add_argument("--max-commits", type=int, default=1500)
    ap.add_argument("--max-prompts", type=int, default=25)
    ap.add_argument("--max-assistant", type=int, default=12)
    ap.add_argument("--cap-user", type=int, default=700)
    ap.add_argument("--cap-assistant", type=int, default=300)
    ap.add_argument("--max-bytes", type=int, default=2_000_000)
    a = ap.parse_args(argv)
    src = set(a.sources.split(","))
    cutoff = time.time() - a.days * 86400
    d = {"generated": dt.datetime.now(dt.timezone.utc).isoformat(), "days": a.days, "git": [], "claude": [], "grok": []}
    if "git" in src:
        repos = find_repos(a.roots.split(","), a.maxdepth)
        d["repos_scanned"] = len(repos)
        d["git"] = collect_git(repos, a.days, a.max_commits)
    if "claude" in src:
        d["claude"] = collect_claude(os.path.expanduser(a.claude_dir), cutoff, a)
    if "grok" in src:
        d["grok"] = collect_grok(os.path.expanduser(a.grok_dir), cutoff, a)
    blob = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    while len(blob.encode()) > a.max_bytes:  # shrink evenly until under budget
        for s in d["claude"] + d["grok"]:
            s["prompts"] = s["prompts"][: max(3, len(s["prompts"]) * 2 // 3)]
            s["assistant"] = s["assistant"][-max(2, len(s["assistant"]) // 2):]
        d["git"] = d["git"][: max(100, len(d["git"]) * 2 // 3)]
        blob = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, f"digest-{dt.date.today()}.json")
    with open(path, "w") as fh:
        fh.write(blob)
    print(f"repos={d.get('repos_scanned', 0)} commits={len(d['git'])} claude={len(d['claude'])} grok={len(d['grok'])} bytes={len(blob.encode())} -> {path}")
    return path


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

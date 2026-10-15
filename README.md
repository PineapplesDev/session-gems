# session-gems

Mine your own week of work for things worth writing about.

`session-gems` reads your recent git commits and your AI coding-agent sessions (Claude Code and Grok build) on your own machine, redacts secrets, and writes one compact JSON digest. A second script groups that digest into themes: what you built, what you fixed, the tools you leaned on, numbers that appeared in the logs, and recurring pain points. Optionally it pulls recent posts from X so you can pair a real piece of work with what people are talking about this week.

Two files, Python 3 standard library only, no install step.

## Privacy model

- **Local only.** `collect.py` makes no network calls. `gems.py` only touches the network if you set `X_BEARER_TOKEN` and pass `--x-query`.
- **Never reads auth or credential files.** Every file open goes through `safe_open`, which refuses any file whose name matches `auth`, `token`, `credential`, `secret`, `password`, `cookie`, `keychain`, `.env`, `.pem`, `.key`, `id_rsa` or `id_ed25519`. For Grok build sessions it opens only `chat_history.jsonl` and `summary.json`. A test enforces this.
- **Messages and stats, not code.** Git collection uses `git log --shortstat`: commit subject, date, short hash, files changed and lines added or removed. No diffs.
- **Redaction** runs on every string before it is stored:
  - private key blocks, JWTs
  - API key and token prefixes (`sk-`, `sk-ant-`, `ghp_`, `github_pat_`, `xox*`, `AKIA`, `AIza`, `ya29`, `glpat`, `whsec`, and others)
  - `Bearer` and `Basic` auth headers
  - `.env` style lines (`SOME_KEY=value`)
  - `password`, `secret`, `token`, `api_key`, `auth`, `cookie`, `session_id` assignments
  - email addresses, phone numbers
  - database URLs and URLs with embedded credentials
  - long hex strings (32+) and long base64 or opaque strings (40+)
  - your home directory, rewritten to `~`
- **Capped.** Per session it keeps at most 25 prompts (700 chars each) and the last 12 assistant messages (300 chars each). The whole digest is trimmed to stay under 2 MB.
- **Review before sharing.** Redaction is pattern based and cannot know which customer names or project details are confidential. Read the digest yourself before you paste it into another tool or share it.

## Usage

```bash
git clone https://github.com/PineapplesDev/session-gems && cd session-gems

# 1. Collect the last 7 days (writes ./out/digest-YYYY-MM-DD.json)
python3 collect.py --days 7 --roots ~/code,~/work

# 2. Cluster into themes
python3 gems.py out/digest-*.json > themes.json

# 3. Optional: add X trend hooks (bring your own token)
X_BEARER_TOKEN=... python3 gems.py out/digest-*.json --x-query "MCP agents" --x-query "Next.js" > themes.json
```

| Flag | Env var | Default | Meaning |
|---|---|---|---|
| `--days` | `GEMS_DAYS` | 7 | Window to collect |
| `--roots` | `GEMS_ROOTS` | `~` | Comma separated dirs to scan for git repos (max depth 4, skips `Library`, `node_modules`, dot dirs) |
| `--sources` | `GEMS_SOURCES` | `git,claude,grok` | Which sources to read |
| `--claude-dir` | `GEMS_CLAUDE_DIR` | `~/.claude/projects` | Claude Code session JSONL |
| `--grok-dir` | `GEMS_GROK_DIR` | `~/.grok/sessions` | Grok build sessions |
| `--out` | `GEMS_OUT` | `./out` | Output folder |
| `--max-commits`, `--max-bytes`, `--cap-user`, `--cap-assistant` | | | Size limits |

Linked git worktrees are skipped, and a commit reachable from several clones is counted once.

Run the tests with `python3 -m unittest discover -s tests`.

## Sample output

> **Example only.** Everything below is synthetic data invented for this README. It is not from a real digest.

`collect.py`:

```
repos=12 commits=84 claude=9 grok=2 bytes=212480 -> out/digest-2030-01-08.json
```

Digest excerpt:

```json
{
  "days": 7,
  "git": [
    {"repo": "~/code/acme-shop", "hash": "3f9c1a2b4d", "date": "2030-01-07T16:02:11-05:00",
     "subject": "fix(checkout): retry the payment webhook instead of dropping it", "stats": "3 files changed, 41 insertions(+), 12 deletions(-)"}
  ],
  "claude": [
    {"source": "claude", "project": "~/code/acme-shop", "start": "2030-01-07T14:10:00Z", "end": "2030-01-07T15:55:00Z",
     "n_prompts": 6, "prompts": [{"ts": "2030-01-07T14:10:00Z", "text": "Webhooks fail about once a day. The key is OPENAI... [ENV_LINE]"}],
     "assistant": [{"ts": "2030-01-07T15:55:00Z", "text": "Retries are in. The test suite passes: 212 tests, 0 failed."}]}
  ]
}
```

`themes.json` excerpt:

```json
{
  "commits_unique": 84,
  "by_repo": [["acme-shop", 40], ["blog", 22]],
  "themes": {
    "fixed": ["2030-01-07 ~/code/acme-shop: fix(checkout): retry the payment webhook instead of dropping it"],
    "pain": ["claude ~/code/acme-shop 2030-01-07: Webhooks fail about once a day..."]
  },
  "numbers": ["claude ~/code/acme-shop 2030-01-07: ...The test suite passes: 212 tests, 0 failed."]
}
```

From there, an idea looks like: *the gem* (a retried webhook, from a commit and a session), *the hook* (a trending post about agents dropping events), and *a format* (short post or longer essay).

## License

MIT

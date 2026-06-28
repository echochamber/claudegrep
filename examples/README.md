# Demo corpus (for screenshots / demos)

`generate_demo.py` writes a tree of **fictional** Claude Code sessions for a
single made-up project — `sidecart`, an embeddable checkout/cart service — so you
can show off claudegrep without exposing any real work. The output uses the real
on-disk format, so claudegrep renders it exactly as it would your own history:
boxes, colors, depth, time ranges, resume handles.

```bash
python3 examples/generate_demo.py ~/Code/sidecart/.sessions
export CLAUDEGREP_PROJECTS_DIR=~/Code/sidecart/.sessions   # search the demo, not ~/.claude
```

Run these in a real terminal (so you get color) and screenshot:

| Command | Shows |
|---------|-------|
| `claudegrep "deploy"` | multi-session result across the project (the hero shot) |
| `claudegrep "cache"` | a focused single-session result |
| `claudegrep "retry"` | a couple of sessions |
| `claudegrep --count "deploy"` | per-project match counts |
| `claudegrep` | the recent-sessions dashboard |
| `claudegrep --list-projects` | the project list |

When you're done, `unset CLAUDEGREP_PROJECTS_DIR` to go back to your real history.

Everything is invented. Session boxes render `~/Code/sidecart`, while
`--count` / `--list-projects` show a neutral `-Users-you-Code-sidecart` — no real
username or project names leak in any view. Change the project with `--project`,
or the displayed home with `--home` (default `~`).

The `CLAUDEGREP_PROJECTS_DIR` override is a normal feature — handy for searching a
copied or archived `~/.claude/projects` too, not just demos.

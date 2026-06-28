#!/usr/bin/env python3
"""Generate a fictional Claude Code corpus for claudegrep screenshots.

Writes fake session transcripts for a single made-up project ("sidecart", an
embeddable checkout/cart service) so you can demo / screenshot claudegrep without
exposing any real work. The output matches the real on-disk format, so claudegrep
renders it exactly as it would your own history — boxes, depth, time ranges,
resume handles.

    python3 examples/generate_demo.py ~/Code/sidecart/.sessions
    export CLAUDEGREP_PROJECTS_DIR=~/Code/sidecart/.sessions
    claudegrep "deploy"

`--project` and `--home` control the project name and the displayed home in
paths (default: sidecart under ~, so they render as ~/Code/sidecart). All content
is invented.
"""

import argparse
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


def J(obj):
    return json.dumps(obj, separators=(",", ":"))


def uuid_like(seed: str) -> str:
    h = hashlib.sha1(seed.encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


# Neutral filler — deliberately avoids the demo search terms (deploy, test,
# cache, retry, …) so searches land on the curated hero lines, not on padding.
FILLER = [
    "Let me check the logs for anything obvious.",
    "Looking at the diff now.",
    "Pushed the change to the branch.",
    "Opened a draft PR for review.",
    "Rebased on main to pick up the latest.",
    "Left a couple of comments inline.",
    "Confirmed the behavior in staging.",
    "Updated the docs to match.",
    "Traced it to the worker pool sizing.",
    "The numbers look better now.",
    "Cleaned up the leftover debug logging.",
    "Reverted the experiment; it didn't help.",
    "Added a changelog entry.",
    "Good catch — fixing that now.",
]

# (ai_title, branch, days_ago, length, [(role, text), ...] hero turns) — one
# coherent project. "deploy" and "test" are woven across several sessions (in
# distinct sentences) so a search for them yields a rich multi-session result.
SESSIONS = [
    ("Fix checkout total rounding bug", "feat/checkout-rounding", 1, 64, [
        ("user", "the checkout total is off by a cent on some carts, can you find the rounding bug"),
        ("assistant", "Found it — we sum floats then round once at the end. Switching to integer cents fixes the off-by-one on tax."),
        ("user", "nice. add a test that would have caught it"),
        ("assistant", "Added a parametrized test over a few tax rates, all green. Deploy is queued behind the next release."),
    ]),
    ("Add Stripe webhook retry handling", "feat/webhook-retries", 2, 90, [
        ("user", "stripe sometimes double-delivers the checkout webhook, we end up charging twice"),
        ("assistant", "We need idempotency: store the event id and no-op on a repeat. Added a retry with backoff for our own downstream call too."),
        ("user", "what happens if redis is down when the webhook lands"),
        ("assistant", "Then we fall back to the DB unique constraint, so a duplicate still can't double-charge. Deployed to staging for a soak test."),
    ]),
    ("Investigate slow product search", "perf/search-index", 4, 120, [
        ("user", "the product search endpoint is taking 2s, can you figure out why"),
        ("assistant", "It's a missing index plus we re-run the query without a cache. Adding a composite index and a short-lived cache."),
        ("user", "how much did the cache help"),
        ("assistant", "p95 dropped from 2.1s to 180ms and the cache hit rate is ~80%. Ready to deploy once the test suite is green."),
    ]),
    ("Add rate limiting to the public API", "feat/rate-limit", 5, 48, [
        ("user", "we're getting hammered by one integration, add rate limiting"),
        ("assistant", "Token-bucket in redis, 100 req/min per key, with a Retry-After header on 429."),
        ("user", "make sure the limit is per-key not global"),
        ("assistant", "Confirmed per-key — added a test that one key's limit doesn't affect another. Deploy plan: shadow mode first, then enforce."),
    ]),
    ("Debug cart-abandonment email job", "fix/abandonment-emails", 6, 140, [
        ("user", "the abandoned-cart emails stopped sending last night, find out why"),
        ("assistant", "The cron job threw on a null cart total and died silently. Added a guard and a dead-letter queue for failures."),
        ("user", "how do we make sure it doesn't silently die again"),
        ("assistant", "Added alerting on job failures plus a retry. Re-ran the backfill and the queue is draining — deploying the fix now."),
    ]),
    ("Add saved-cart persistence across devices", "feat/saved-carts", 8, 72, [
        ("user", "i want carts to persist across devices when you're logged in, design it"),
        ("assistant", "Store the cart server-side keyed by user, versioned so we can migrate the schema. Merge the guest cart on login."),
        ("user", "what about conflicts if two devices edit the cart"),
        ("assistant", "Last-write-wins per line item, with a test for the merge. The migration for existing local carts is reversible."),
    ]),
    ("Add multi-currency price display", "feat/multi-currency", 10, 38, [
        ("user", "add multi-currency price display, default from the shopper's locale"),
        ("assistant", "Convert at request time from a cached rate table, rounding per-currency to avoid the half-cent issue. Config sets the supported set."),
        ("user", "ship it to a few markets first"),
        ("assistant", "Done — feature-flagged to CA/UK and deployed behind the flag. Will widen once the numbers look right."),
    ]),
    # No ai-title on this one, to show the first-message topic fallback.
    (None, "main", 13, 96, [
        ("user", "the checkout E2E test is flaky in CI, fails maybe 1 in 5 runs"),
        ("assistant", "It's a race on the auth redirect — the test asserts before the cookie is set. Added an explicit wait and a retry."),
        ("user", "can we make it deterministic instead of retrying"),
        ("assistant", "Yes — stubbed the auth callback so there's no real redirect timing. The test is deterministic now over 50 runs."),
    ]),
]


def build_session(spec, project, cwd, now, projects_dir):
    title, branch, days_ago, target_len, hero = spec
    sid = uuid_like(f"{project}-{days_ago}-{title}")
    # The project DIR name (shown by --count / --list-projects) is independent of
    # the displayed cwd, so use a neutral encoding here — the box still renders
    # `cwd` (which may use the real home for a ~ display) without leaking it.
    proj_dir = projects_dir / f"-Users-you-Code-{project}"
    proj_dir.mkdir(parents=True, exist_ok=True)

    start = now - timedelta(days=days_ago, hours=2)
    lines = []
    if title:
        lines.append(J({"type": "ai-title", "aiTitle": title, "sessionId": sid}))

    # Filler turns before the hero exchange so the matched depth looks realistic.
    turns = []
    for i in range((target_len - len(hero)) // 2):
        turns.append(("user", FILLER[i % len(FILLER)]))
        turns.append(("assistant", FILLER[(i + 7) % len(FILLER)]))
    cut = int(len(turns) * 0.66)  # drop the hero exchange ~2/3 of the way in
    turns = turns[:cut] + hero + turns[cut:]

    ts = start
    for idx, (role, text) in enumerate(turns):
        ts = ts + timedelta(minutes=2, seconds=(idx * 7) % 50)
        stamp = ts.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        content = text if role == "user" else [{"type": "text", "text": text}]
        lines.append(J({
            "type": role, "sessionId": sid, "uuid": uuid_like(f"{sid}-{idx}"),
            "timestamp": stamp, "gitBranch": branch, "cwd": cwd,
            "userType": "external", "message": {"role": role, "content": content},
        }))
    lines.append(J({"type": "file-history-snapshot", "messageId": uuid_like(sid + "fh")}))

    f = proj_dir / f"{sid}.jsonl"
    f.write_text("\n".join(lines) + "\n")
    os.utime(f, (ts.timestamp(), ts.timestamp()))  # mtime = last activity
    return f


def main():
    ap = argparse.ArgumentParser(description="Generate a demo Claude Code corpus for claudegrep screenshots.")
    ap.add_argument("dest", nargs="?", default="demo-projects",
                    help="output projects dir (default: ./demo-projects)")
    ap.add_argument("--project", default="sidecart", help="project name (default: sidecart)")
    ap.add_argument("--home", default="~",
                    help="displayed home in paths (default: ~ → renders as ~/Code/<project>)")
    args = ap.parse_args()

    home = os.path.expanduser(args.home).rstrip("/")
    cwd = f"{home}/Code/{args.project}"
    dest = Path(os.path.expanduser(args.dest)).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    now = datetime(2026, 6, 28, 18, 0, 0, tzinfo=timezone.utc)  # fixed for reproducibility

    written = [build_session(s, args.project, cwd, now, dest) for s in SESSIONS]
    print(f"Wrote {len(written)} demo sessions for '{args.project}' ({cwd}) to {dest}")
    print()
    print("Point claudegrep at it (run in a real terminal for colors):")
    print(f'  export CLAUDEGREP_PROJECTS_DIR="{dest}"')
    print('  claudegrep "deploy"       # multi-session result')
    print('  claudegrep "cache"')
    print('  claudegrep --count "deploy"')
    print('  claudegrep                # recent-sessions dashboard')


if __name__ == "__main__":
    main()

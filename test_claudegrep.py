"""Tests for claudegrep. Run: pytest test_claudegrep.py

Loads the extension-less `claudegrep` script as a module and exercises it both
as unit functions and end-to-end via main() against a synthetic ~/.claude
projects tree. Where it matters, each end-to-end case runs twice — with rg and
with rg forced absent — to prove the fast (rg) and full (Python) paths agree.
"""

import importlib.util
import json
import os
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

# The entry script has no .py extension; load it with an explicit source loader.
_LOADER = SourceFileLoader("claudegrep", str(Path(__file__).parent / "claudegrep"))
_SPEC = importlib.util.spec_from_loader("claudegrep", _LOADER)
cg = importlib.util.module_from_spec(_SPEC)
_LOADER.exec_module(cg)


# ── Fixture builders ──────────────────────────────────────────────────────────

SID1 = "11111111-1111-1111-1111-111111111111"
SID2 = "22222222-2222-2222-2222-222222222222"
SID3 = "33333333-3333-3333-3333-333333333333"


def J(obj):
    # Claude Code writes COMPACT json — the byte-gate fast path depends on it.
    return json.dumps(obj, separators=(",", ":"))


def user_text(text, sid, ts, uuid, branch="main", cwd="/repo", **extra):
    return J({
        "type": "user", "sessionId": sid, "uuid": uuid, "timestamp": ts,
        "gitBranch": branch, "cwd": cwd, "userType": "external",
        "message": {"role": "user", "content": text}, **extra})


def assistant(blocks, sid, ts, uuid, branch="main", cwd="/repo"):
    return J({
        "type": "assistant", "sessionId": sid, "uuid": uuid, "timestamp": ts,
        "gitBranch": branch, "cwd": cwd, "userType": "external",
        "message": {"role": "assistant", "content": blocks}})


def tool_result(content, sid, ts, uuid):
    return J({
        "type": "user", "sessionId": sid, "uuid": uuid, "timestamp": ts,
        "gitBranch": "main", "cwd": "/repo", "userType": "external",
        "message": {"role": "user",
                    "content": [{"type": "tool_result", "content": content}]}})


def ai_title(title, sid):
    return J({"type": "ai-title", "aiTitle": title, "sessionId": sid})


def noise():
    # untimed metadata records the tool must skip without choking
    return [J({"type": "last-prompt", "leafUuid": "x", "sessionId": SID1}),
            J({"type": "file-history-snapshot", "messageId": "y"}),
            J({"type": "attachment", "sessionId": SID1})]


def write_session(projects: Path, project: str, sid: str, lines, mtime=None):
    d = projects / project
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{sid}.jsonl"
    f.write_text("\n".join(lines) + "\n")
    if mtime is not None:
        os.utime(f, (mtime, mtime))
    return f


@pytest.fixture
def projects(tmp_path, monkeypatch):
    """A synthetic ~/.claude/projects with three sessions of known content."""
    p = tmp_path / "projects"
    # Session 1 (oldest) — project alpha
    write_session(p, "alpha", SID1, [
        ai_title("Alpha topic about widgets", SID1),
        user_text("please fix the widget alignment bug", SID1, "2026-06-01T10:00:00.000Z", "u1"),
        assistant([{"type": "thinking", "thinking": ""},
                   {"type": "text", "text": "Fixed the widget alignment."},
                   {"type": "tool_use", "name": "Bash",
                    "input": {"command": "grep WIDGET_SECRET config"}}],
                  SID1, "2026-06-01T10:01:00.000Z", "a1"),
        *noise(),
    ], mtime=1000)
    # Session 2 (middle) — project beta. "widget" is in the user turn;
    # "tooltoken" appears ONLY inside a tool_result (the surface test relies on
    # this being invisible by default).
    write_session(p, "beta", SID2, [
        ai_title("Beta deploy investigation", SID2),
        user_text("why did the widget deploy fail", SID2, "2026-06-10T09:00:00.000Z", "u2", branch="dev"),
        tool_result("error: tooltoken service crashed at line 42", SID2,
                    "2026-06-10T09:00:30.000Z", "a2"),
        assistant([{"type": "text", "text": "The deploy failed for an unrelated reason."}],
                  SID2, "2026-06-10T09:01:00.000Z", "a3"),
    ], mtime=2000)
    # Session 3 (newest) — project alpha again
    write_session(p, "alpha", SID3, [
        ai_title("Alpha follow-up on widgets", SID3),
        user_text("the widget bug is back", SID3, "2026-06-20T08:00:00.000Z", "u3"),
        assistant([{"type": "text", "text": "Looking at the widget code now."}],
                  SID3, "2026-06-20T08:00:30.000Z", "a4"),
    ], mtime=3000)
    monkeypatch.setattr(cg, "PROJECTS_DIR", p)
    return p


def run(argv, monkeypatch, disable=(), env=None):
    """Run main(argv) capturing stdout. `disable` hides binaries from
    shutil.which to force a backend: () = rg, ("rg",) = grep, ("rg","grep") =
    pure Python."""
    import io
    import contextlib
    if disable:
        hidden = set(disable)
        monkeypatch.setattr(cg.shutil, "which",
                            lambda name: None if name in hidden else _real_which(name))
    if env:
        for k, v in env.items():
            monkeypatch.setenv(k, v)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cg.main(argv)
    return rc, buf.getvalue()


_real_which = cg.shutil.which

# The three backend tiers, as `disable` sets for parametrized tests.
BACKENDS = [(), ("rg",), ("rg", "grep")]
BACKEND_IDS = ["rg", "grep", "python"]


def parse_args(argv):
    args = cg.build_parser().parse_args(argv)
    if args.pattern:
        cg.resolve_case_sensitivity(args)
    return args


# ── Unit: surface extraction ─────────────────────────────────────────────────

def test_record_text_string():
    rec = {"message": {"content": "hello world"}}
    assert cg.record_text(rec, all_content=False) == "hello world"


def test_record_text_text_blocks_only_by_default():
    rec = {"message": {"content": [
        {"type": "text", "text": "visible prose"},
        {"type": "thinking", "thinking": ""},
        {"type": "tool_use", "name": "Bash", "input": {"command": "secret cmd"}},
    ]}}
    assert cg.record_text(rec, all_content=False) == "visible prose"
    out = cg.record_text(rec, all_content=True)
    assert "visible prose" in out and "secret cmd" in out and "Bash" in out


def test_record_text_tool_result_string_and_array():
    rec_s = {"message": {"content": [{"type": "tool_result", "content": "err 42"}]}}
    assert cg.record_text(rec_s, all_content=False) == ""
    assert "err 42" in cg.record_text(rec_s, all_content=True)
    rec_a = {"message": {"content": [{"type": "tool_result", "content": [
        {"type": "text", "text": "nested out"}, {"type": "image"}]}]}}
    assert "nested out" in cg.record_text(rec_a, all_content=True)


# ── Unit: display width ──────────────────────────────────────────────────────

def test_display_width_and_pad():
    assert cg.display_width("abc") == 3
    assert cg.display_width("日本") == 4          # wide chars = 2 cells
    assert cg.display_width("café") == 4
    assert cg.pad_to("ab", 5) == "ab   "
    assert cg.display_width(cg.pad_to("日本", 10)) == 10
    assert cg.truncate_to_width("hello", 3) == "hel"
    assert cg.display_width(cg.truncate_to_width("日本語テスト", 5)) <= 5


# ── Unit: timestamps ─────────────────────────────────────────────────────────

def test_fmt_ts():
    assert cg.fmt_ts_short("2026-06-20T08:05:00.000Z") == "08:05"
    assert cg.fmt_ts_long("2026-06-20T08:05:00.000Z") == "Jun 20, 08:05"
    assert cg.fmt_ts_long("") == ""
    assert cg.fmt_ts_short("garbage") == ""


# ── Unit: arg parsing / format ───────────────────────────────────────────────

def test_n_is_alias_for_m():
    assert parse_args(["-n", "7", "x"]).max_count == 7
    assert parse_args(["-m", "9", "x"]).max_count == 9


def test_combined_short_flags():
    a = parse_args(["-un", "3", "foo"])
    assert a.user_only and a.max_count == 3 and a.pattern == "foo"


def test_double_dash_pattern():
    a = parse_args(["--", "--weird"])
    assert a.pattern == "--weird"


def test_smart_case():
    assert parse_args(["foo"]).case_sensitive is False
    assert parse_args(["Foo"]).case_sensitive is True
    assert parse_args(["-i", "Foo"]).case_sensitive is False
    assert parse_args(["-s", "foo"]).case_sensitive is True


def test_resolve_format(monkeypatch):
    monkeypatch.setattr(cg.sys.stdout, "isatty", lambda: False, raising=False)
    assert cg.resolve_format(parse_args(["x"])) == "plain"
    monkeypatch.setattr(cg.sys.stdout, "isatty", lambda: True, raising=False)
    assert cg.resolve_format(parse_args(["x"])) == "rich"
    assert cg.resolve_format(parse_args(["--json", "x"])) == "json"
    monkeypatch.setenv("CLAUDEGREP_MODE", "plain")
    assert cg.resolve_format(parse_args(["x"])) == "plain"


def test_color_enabled(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert cg.color_enabled("rich", parse_args(["x"])) is True
    assert cg.color_enabled("plain", parse_args(["x"])) is False
    monkeypatch.setenv("NO_COLOR", "1")
    assert cg.color_enabled("rich", parse_args(["x"])) is False


def test_fixed_strings_and_word():
    rx = cg.compile_pattern(parse_args(["-F", "a.b"]))
    assert rx.search("a.b") and not rx.search("axb")
    rxw = cg.compile_pattern(parse_args(["-w", "cat"]))
    assert rxw.search("a cat sat") and not rxw.search("category")


# ── End-to-end ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("disable", BACKENDS, ids=BACKEND_IDS)
def test_basic_search_plain(projects, monkeypatch, disable):
    rc, out = run(["widget", "--plain", "--no-pager"], monkeypatch, disable=disable)
    assert rc == 0
    # all three sessions mention "widget" in conversation text
    assert "Alpha follow-up on widgets" in out
    assert "Beta deploy investigation" in out
    assert SID3 in out  # resume id present


@pytest.mark.parametrize("disable", BACKENDS, ids=BACKEND_IDS)
def test_recency_ordering(projects, monkeypatch, disable):
    rc, out = run(["widget", "--grep", "--no-pager"], monkeypatch, disable=disable)
    # newest session (SID3, mtime 3000) should appear before oldest (SID1)
    assert out.index(SID3) < out.index(SID1)


def test_all_backends_agree(projects, monkeypatch):
    # rg, grep, and pure-Python must produce identical output.
    outs = [run(["widget", "--grep", "--no-pager"], monkeypatch, disable=d)[1]
            for d in BACKENDS]
    assert outs[0].strip()
    assert outs[0] == outs[1] == outs[2]


def test_grep_backend_is_chosen_when_rg_absent(projects, monkeypatch):
    monkeypatch.setattr(cg.shutil, "which",
                        lambda n: None if n == "rg" else _real_which(n))
    assert cg.choose_backend(parse_args(["widget"])) == "grep"
    # a Perl-ism POSIX grep can't be trusted with → fall through to Python
    assert cg.choose_backend(parse_args([r"\bwidget\b"])) is None


def test_default_surface_excludes_tool_result(projects, monkeypatch):
    # "tooltoken" lives only in a tool_result (beta) → not found by default …
    _, out = run(["tooltoken", "--plain", "--no-pager"], monkeypatch)
    assert "no matches" in out.lower()
    # … but found with --all-content
    _, out2 = run(["tooltoken", "--all-content", "--plain", "--no-pager"], monkeypatch)
    assert "Beta deploy investigation" in out2


def test_all_content_hint_on_tool_only_term(projects, monkeypatch):
    _, out = run(["tooltoken", "--plain", "--no-pager"], monkeypatch)
    assert "--all-content" in out  # nudge to widen the surface


def test_user_only_filter(projects, monkeypatch):
    _, out = run(["widget", "-u", "--grep", "--no-pager"], monkeypatch)
    # only user turns; assistant "Looking at the widget code" must be absent
    assert "Looking at the widget code" not in out
    assert "the widget bug is back" in out


def test_assistant_only_filter(projects, monkeypatch):
    _, out = run(["widget", "-a", "--grep", "--no-pager"], monkeypatch)
    assert "the widget bug is back" not in out
    assert "Looking at the widget code" in out


def test_project_basename_filter(projects, monkeypatch):
    _, out = run(["widget", "-p", "beta", "--grep", "--no-pager"], monkeypatch)
    assert SID2 in out and SID1 not in out and SID3 not in out


def test_session_filter(projects, monkeypatch):
    _, out = run(["widget", "--session", SID1, "--grep", "--no-pager"], monkeypatch)
    assert SID1 in out and SID3 not in out


def test_json_output_shape(projects, monkeypatch):
    rc, out = run(["widget", "--json", "-m", "1"], monkeypatch)
    data = json.loads(out)
    assert isinstance(data, list) and len(data) == 1
    rowkeys = set(data[0])
    assert {"sessionId", "timestamp", "type", "resume", "text", "pos",
            "total", "file", "lineno"} <= rowkeys
    assert data[0]["resume"].startswith("claude --resume ")


def test_count_output(projects, monkeypatch):
    rc, out = run(["widget", "--count"], monkeypatch)
    assert "matches across" in out
    assert "alpha" in out and "beta" in out


def test_position_index_enrichment(projects, monkeypatch):
    rc, out = run(["bug", "--json", "-m", "5"], monkeypatch)
    data = json.loads(out)
    # SID1 user "fix the widget alignment bug" is the 2nd convo record (after the
    # ai-title, which is not counted): pos among user+assistant = 1, total = 2.
    s1 = [d for d in data if d["sessionId"] == SID1][0]
    assert s1["pos"] == 1 and s1["total"] == 2 and s1["upos"] == 1


def test_no_matches_clean_exit(projects, monkeypatch):
    rc, out = run(["zzznotfound", "--plain", "--no-pager"], monkeypatch)
    assert rc == 0 and "no matches" in out.lower()


def test_list_projects(projects, monkeypatch):
    rc, out = run(["--list-projects"], monkeypatch)
    assert "alpha" in out and "beta" in out


def test_bare_invocation_dashboard(projects, monkeypatch):
    rc, out = run([], monkeypatch)
    assert rc == 0
    assert "recent sessions" in out.lower()
    assert "claude --resume" in out


def test_rich_box_alignment(projects, monkeypatch):
    rc, out = run(["widget", "--rich", "--no-color", "--no-pager"], monkeypatch)
    # every box border row must have its right '│' at the same column
    rights = [line.index("│", line.index("│") + 1)
              for line in out.splitlines() if line.count("│") == 2]
    assert rights and len(set(rights)) == 1


def test_days_filter(projects, monkeypatch):
    # everything in the fixture predates "today" by far; --days 1 → nothing
    rc, out = run(["widget", "--days", "1", "--plain", "--no-pager"], monkeypatch)
    assert "no matches" in out.lower() or "0 of" in out


def test_max_count_validation(projects, monkeypatch):
    rc, out = run(["widget", "-m", "0", "--no-pager"], monkeypatch)
    assert rc == 2


def test_projects_dir_env_override(monkeypatch):
    monkeypatch.setenv("CLAUDEGREP_PROJECTS_DIR", "/tmp/cg-demo-x")
    assert str(cg._resolve_projects_dir()) == "/tmp/cg-demo-x"
    monkeypatch.delenv("CLAUDEGREP_PROJECTS_DIR", raising=False)
    assert cg._resolve_projects_dir() == cg.Path(os.path.expanduser("~/.claude/projects"))


def test_user_assistant_mutually_exclusive(projects, monkeypatch):
    with pytest.raises(SystemExit):
        cg.build_parser().parse_args(["-u", "-a", "x"])


def test_no_false_more_flag(projects, monkeypatch):
    # only 4 widget matches total and -m is far higher → no "N+" / "more" footer
    rc, out = run(["widget", "--plain", "--no-pager", "-m", "50"], monkeypatch)
    header = out.splitlines()[0]
    assert "+" not in header  # exact count, not a lower bound
    assert not any("more — raise" in ln for ln in out.splitlines())


def test_subagent_renders_as_separate_session(tmp_path, monkeypatch):
    # parent + subagent share a sessionId but are distinct sessions/files
    p = tmp_path / "projects"
    write_session(p, "proj", SID1, [
        ai_title("Parent task", SID1),
        user_text("parent mentions zebra here", SID1, "2026-06-01T10:00:00.000Z", "u1"),
    ], mtime=1000)
    sub = p / "proj" / SID1 / "subagents"
    sub.mkdir(parents=True)
    f = sub / "agent-abc.jsonl"
    f.write_text("\n".join([
        J({"type": "user", "sessionId": SID1, "uuid": "s1", "isSidechain": True,
           "timestamp": "2026-06-01T10:00:05.000Z", "gitBranch": "main", "cwd": "/repo",
           "userType": "external", "message": {"role": "user", "content": "subagent zebra work"}}),
    ]) + "\n")
    os.utime(f, (1000, 1000))
    monkeypatch.setattr(cg, "PROJECTS_DIR", p)
    rc, out = run(["zebra", "--include-subagents", "--plain", "--no-pager"], monkeypatch)
    assert "↳ " in out                       # subagent marker present
    assert "agent-abc.jsonl" in out          # subagent file path, not just parent
    assert out.count("## ") == 2             # two distinct session headers


def test_content_recency_beats_mtime(tmp_path, monkeypatch):
    # Session A: newer mtime, OLDER content. Session B: older mtime, NEWER content.
    # The newest-content session (B) must win the single display slot.
    p = tmp_path / "projects"
    write_session(p, "a", SID1, [
        ai_title("Older content newer mtime", SID1),
        user_text("quokka one", SID1, "2026-01-01T00:00:00.000Z", "u1"),
    ], mtime=9000)
    write_session(p, "b", SID2, [
        ai_title("Newer content older mtime", SID2),
        user_text("quokka two", SID2, "2026-06-01T00:00:00.000Z", "u2"),
    ], mtime=1000)
    monkeypatch.setattr(cg, "PROJECTS_DIR", p)
    rc, out = run(["quokka", "--plain", "--no-pager", "-m", "1"], monkeypatch)
    assert SID2 in out and SID1 not in out

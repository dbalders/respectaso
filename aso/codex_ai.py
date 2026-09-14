"""Local Codex CLI adapter using its existing ChatGPT login, never API keys."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from django.conf import settings
from django.utils import timezone

from . import run_queue
from .models import CodexRun, Keyword, SearchResult

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "analysis": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "title": {"type": "string"}, "subtitle": {"type": "string"},
        "keyword_field": {"type": "string"},
        "cautions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["analysis", "keywords", "title", "subtitle", "keyword_field", "cautions"],
}


def executable():
    candidates = [os.environ.get("RESPECTASO_CODEX_BIN"), shutil.which("codex"),
                  "/Applications/ChatGPT.app/Contents/Resources/codex",
                  "/Applications/Codex.app/Contents/Resources/codex"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise RuntimeError("Codex CLI was not found. Install Codex and sign in with ChatGPT.")


def cli_env():
    # Keep native credential lookup, but don't inherit API keys or turn/session settings.
    keep = {"HOME", "PATH", "TMPDIR", "LANG", "USER", "LOGNAME", "CODEX_HOME"}
    return {k: v for k, v in os.environ.items() if k in keep}


def connection_status():
    try:
        r = subprocess.run([executable(), "login", "status"], capture_output=True,
                           text=True, env=cli_env(), timeout=15)
        connected = r.returncode == 0 and "chatgpt" in (r.stdout + r.stderr).lower()
        return {"connected": connected, "message": "Connected with ChatGPT" if connected else
                "Sign in with ChatGPT using codex login in Terminal. API-key login is not used here."}
    except (OSError, subprocess.TimeoutExpired, RuntimeError):
        return {"connected": False, "message": "Codex CLI unavailable. Install Codex and run codex login."}


def ask_codex(prompt):
    if not connection_status()["connected"]:
        raise RuntimeError("Codex is not signed in with ChatGPT. Run codex login in Terminal, then retry.")
    with tempfile.TemporaryDirectory(prefix="respectaso-codex-") as directory:
        root = Path(directory)
        schema = root / "schema.json"
        output = root / "report.json"
        schema.write_text(json.dumps(SCHEMA))
        args = [executable(), "exec", "--ignore-user-config", "--ephemeral",
                "--skip-git-repo-check", "--sandbox", "read-only", "--cd", directory,
                "-c", 'forced_login_method="chatgpt"',
                "-c", 'approval_policy="never"', "-c", 'web_search="disabled"',
                "-c", "features.shell_tool=false", "-c", "features.apply_patch=false",
                "-c", "project_doc_max_bytes=0",
                "--output-schema", str(schema), "--output-last-message", str(output), "-"]
        try:
            result = subprocess.run(args, input=prompt, capture_output=True, text=True,
                                    env=cli_env(), timeout=900)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Codex exceeded 15 minutes. Retry the analysis with a shorter brief.") from exc
        if result.returncode != 0:
            diagnostic = (result.stderr + result.stdout).lower()
            if any(word in diagnostic for word in ("usage limit", "rate limit", "quota")):
                raise RuntimeError("Your Codex usage limit was reached. Retry after your subscription allowance resets.")
            raise RuntimeError("Codex could not complete the request. Check Codex login and subscription availability, then retry.")
        try:
            report = json.loads(output.read_text())
            if set(report) != set(SCHEMA["required"]):
                raise ValueError("Invalid report fields")
            for key in ("analysis", "title", "subtitle", "keyword_field"):
                if not isinstance(report[key], str):
                    raise ValueError("Invalid text field")
            for key in ("keywords", "cautions"):
                if not isinstance(report[key], list) or not all(isinstance(v, str) for v in report[key]):
                    raise ValueError("Invalid list field")
            report["keywords"] = list(dict.fromkeys(k.strip() for k in report["keywords"] if k.strip()))[:30]
            for key, limit in (("title", 30), ("subtitle", 30), ("keyword_field", 100)):
                if len(report[key]) > limit:
                    report["cautions"].append(f"{key.replace('_', ' ').title()} is {len(report[key])} characters; shorten to {limit} before publishing.")
            return report
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError("Codex returned an invalid report. Retry this analysis.") from exc


def compact_evidence(result):
    from .keyword_scoring import result_payload
    data = result_payload(result)
    return {"keyword": data["keyword"], "country": data["country"],
            "researched_at": result.searched_at.isoformat(),
            "popularity": data["popularity_score"], "difficulty": data["difficulty_score"],
            "popularity_source": data.get("popularity_source", "See dataset settings"),
            "apple_popularity": data.get("popularity_apple"),
            "opportunity": data["opportunity_score"], "competitors": data["competitors"][:10]}


def execute(pk):
    row = CodexRun.objects.get(pk=pk)
    try:
        from .research_pipeline import run
        report, evidence, apple = run(row, ask_codex, compact_evidence)
        CodexRun.objects.filter(pk=pk).update(status="completed", report=report, evidence=evidence, discovery_data=apple,
                    progress_message="Complete", finished_at=timezone.now(), error_message="")
    except Exception as exc:
        # Provider output and auth diagnostics are deliberately never returned to the browser.
        message = str(exc) if isinstance(exc, RuntimeError) else "Research could not complete. Check the local connection and retry."
        CodexRun.objects.filter(pk=pk).update(status="failed", error_message=message,
                    progress_message="Failed", finished_at=timezone.now())


run_queue.register(run_queue.Feature(
    key="codex", label="Codex AI", model=CodexRun, filter_kwargs={}, execute=execute,
    describe=lambda row: {"label": row.mode.title(), "detail": row.brief[:100], "country": row.country, "is_refinement": False},
    open_url="/codex/",
))

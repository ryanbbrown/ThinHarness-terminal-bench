from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def test_run_script_accepts_codex_chatgpt_status_from_stderr_without_echoing_it(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parent.parent
    commands = tmp_path / "uv-commands"
    _executable(
        tmp_path / "codex",
        "#!/bin/sh\nprintf '%s\\n' 'private-status-detail' >&2\nprintf '%s\\n' 'Logged in using ChatGPT' >&2\n",
    )
    _executable(
        tmp_path / "uv",
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >>\"$UV_COMMANDS\"\n",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{tmp_path}:{environment['PATH']}",
            "TB_THINHARNESS_LOCAL_SOURCE": str(tmp_path),
            "UV_COMMANDS": str(commands),
        }
    )
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"):
        environment.pop(name, None)

    completed = subprocess.run(
        [str(root / "scripts" / "run-subscription-smoke.sh")],
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "private-status-detail" not in completed.stdout + completed.stderr
    assert commands.read_text().splitlines() == [
        "run python -m tbench.subscription_launch run",
        "run python -m tbench.subscription_validate finalize-run artifacts/codex-subscription-crack-7z-recovery --report "
        "reports/codex-subscription-crack-7z-recovery.json",
    ]

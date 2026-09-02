"""Regression test suite for Launcher Pipe Output Handling (Phase S3)."""

import os
import subprocess
import sys
import time
from pathlib import Path

def test_launcher_file_sinks_large_output(tmp_path):
    """Verify child emitting large stdout/stderr does not block or stall when file sinks are used."""
    stdout_file = tmp_path / "test_runner_stdout.log"
    stderr_file = tmp_path / "test_runner_stderr.log"

    # Python script that prints 50,000 lines of output to stdout and stderr
    script = (
        "import sys\n"
        "for i in range(50000):\n"
        "    sys.stdout.write(f'STDOUT line {i}\\n')\n"
        "    sys.stderr.write(f'STDERR line {i}\\n')\n"
        "sys.stdout.flush()\n"
        "sys.stderr.flush()\n"
    )
    script_path = tmp_path / "heavy_writer.py"
    script_path.write_text(script, encoding="utf-8")

    with stdout_file.open("a", encoding="utf-8") as out, stderr_file.open("a", encoding="utf-8") as err:
        proc = subprocess.Popen(
            [sys.executable, str(script_path)],
            stdout=out,
            stderr=err,
            stdin=subprocess.DEVNULL,
        )
        exit_code = proc.wait(timeout=15)

    assert exit_code == 0
    assert stdout_file.exists()
    assert stderr_file.exists()

    stdout_lines = stdout_file.read_text(encoding="utf-8").splitlines()
    stderr_lines = stderr_file.read_text(encoding="utf-8").splitlines()

    assert len(stdout_lines) == 50000
    assert len(stderr_lines) == 50000
    assert "STDOUT line 49999" in stdout_lines[-1]
    assert "STDERR line 49999" in stderr_lines[-1]

#!/usr/bin/env python3
# Copyright Advanced Micro Devices, Inc.
# SPDX-License-Identifier: MIT

"""Validates the hosted Python tool cache and removes entries that are unusable.

`actions/setup-python` treats a cached Python as valid when the version's arch
directory and its sibling `<arch>.complete` marker both exist. It never runs the
interpreter, so a partially deleted entry keeps being selected: the action logs
"Successfully set up CPython" and prepends a directory whose console scripts
point at a missing interpreter. The first `pip` invocation then dies with
"cannot execute: required file not found" and exit code 127.

Because the `.complete` marker outlives the job, the same broken entry is
re-selected on every subsequent run, so the failure never self-heals and
re-running the workflow cannot help (see ROCm/TheRock#7370, where every test
component job on one gfx1150 runner failed this way for days).

Running this before `actions/setup-python` executes each candidate interpreter
and deletes both the arch directory and its `.complete` marker when it does not
work, which makes the action fall back to a fresh download and install.

Example usage:

    python clean_python_toolcache.py --python-version 3.12
"""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

# Interpreters shipped by actions/python-versions link against the libpython in
# their own `lib` directory, so it must be on the loader path or a healthy entry
# reports the system Python's version and no `pip` module.
_LIBRARY_PATH_VARS = {
    "linux": "LD_LIBRARY_PATH",
    "darwin": "DYLD_FALLBACK_LIBRARY_PATH",
}

_VALIDATION_TIMEOUT_SECONDS = 60


def get_toolcache_root() -> Path | None:
    """Returns the hosted tool cache root, or None if the runner defines none."""
    root = os.environ.get("AGENT_TOOLSDIRECTORY") or os.environ.get("RUNNER_TOOL_CACHE")
    return Path(root) if root else None


def get_interpreter_path(arch_dir: Path) -> Path:
    if sys.platform == "win32":
        return arch_dir / "python.exe"
    return arch_dir / "bin" / "python"


def get_console_script_paths(arch_dir: Path) -> list[Path]:
    if sys.platform == "win32":
        return [arch_dir / "Scripts" / "pip.exe"]
    return [arch_dir / "bin" / "pip"]


def _run(command: list[str], arch_dir: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    library_path_var = _LIBRARY_PATH_VARS.get(sys.platform)
    if library_path_var:
        lib_dir = str(arch_dir / "lib")
        existing = env.get(library_path_var)
        env[library_path_var] = (
            f"{lib_dir}{os.pathsep}{existing}" if existing else lib_dir
        )
    return subprocess.run(
        command,
        env=env,
        capture_output=True,
        text=True,
        timeout=_VALIDATION_TIMEOUT_SECONDS,
    )


def validate_entry(arch_dir: Path) -> str | None:
    """Returns None if the tool cache entry is usable, else why it is not."""
    interpreter = get_interpreter_path(arch_dir)
    if not interpreter.exists():
        return f"interpreter {interpreter} does not exist"

    checks = [[str(interpreter), "-m", "pip", "--version"]]
    # Console scripts fail independently of the interpreter: they carry an
    # absolute shebang, which is what bash reports as exit 127.
    checks += [
        [str(script), "--version"]
        for script in get_console_script_paths(arch_dir)
        if script.exists()
    ]

    for command in checks:
        try:
            result = _run(command, arch_dir)
        except OSError as e:
            return f"{command[0]} could not be executed: {e}"
        except subprocess.TimeoutExpired:
            return f"{command[0]} timed out after {_VALIDATION_TIMEOUT_SECONDS}s"
        if result.returncode != 0:
            output = (result.stderr or result.stdout).strip().splitlines()
            detail = output[-1] if output else "no output"
            return f"`{' '.join(command)}` exited with {result.returncode}: {detail}"

    return None


def remove_entry(arch_dir: Path) -> None:
    """Removes an arch directory and the marker that keeps setup-python using it."""
    shutil.rmtree(arch_dir, ignore_errors=True)
    # Deleting the marker is what actually invalidates the entry: it is the only
    # artifact setup-python inspects when looking for a cached version.
    complete_marker = arch_dir.parent / f"{arch_dir.name}.complete"
    complete_marker.unlink(missing_ok=True)


def find_entries(toolcache_root: Path, python_version: str) -> list[Path]:
    """Returns arch directories cached for `python_version` (e.g. `3.12`)."""
    python_toolcache = toolcache_root / "Python"
    if not python_toolcache.is_dir():
        return []

    entries = []
    for version_dir in sorted(python_toolcache.iterdir()):
        if not version_dir.is_dir():
            continue
        if version_dir.name != python_version and not version_dir.name.startswith(
            f"{python_version}."
        ):
            continue
        entries += [
            arch_dir for arch_dir in sorted(version_dir.iterdir()) if arch_dir.is_dir()
        ]
    return entries


def clean_toolcache(toolcache_root: Path | None, python_version: str) -> int:
    """Removes unusable cache entries, returning how many were removed."""
    if toolcache_root is None:
        print("No hosted tool cache configured, nothing to validate.")
        return 0

    entries = find_entries(toolcache_root, python_version)
    if not entries:
        print(f"No cached Python {python_version} entries under {toolcache_root}.")
        return 0

    removed = 0
    for arch_dir in entries:
        error = validate_entry(arch_dir)
        if error is None:
            print(f"Python tool cache entry {arch_dir} is usable.")
            continue
        print(f"Python tool cache entry {arch_dir} is unusable ({error}), removing it.")
        remove_entry(arch_dir)
        removed += 1

    return removed


def main(argv: list[str] | None = None):
    p = argparse.ArgumentParser(prog="clean_python_toolcache.py")
    p.add_argument(
        "--python-version",
        required=True,
        type=str,
        help="Python version requested from actions/setup-python (e.g. 3.12)",
    )
    args = p.parse_args(argv)

    removed = clean_toolcache(get_toolcache_root(), args.python_version)
    if removed:
        print(f"Removed {removed} unusable Python tool cache entrie(s).")


if __name__ == "__main__":
    main()

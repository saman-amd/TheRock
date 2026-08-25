#!/usr/bin/env python3
# Copyright Advanced Micro Devices, Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for clean_python_toolcache.py"""

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

import clean_python_toolcache
from clean_python_toolcache import (
    clean_toolcache,
    find_entries,
    get_toolcache_root,
    remove_entry,
    validate_entry,
)

IS_WINDOWS = sys.platform == "win32"


def make_entry(toolcache_root: Path, version: str, arch: str = "x64") -> Path:
    """Creates a tool cache entry whose interpreter is a working stub."""
    arch_dir = toolcache_root / "Python" / version / arch
    (arch_dir / "lib").mkdir(parents=True)

    if IS_WINDOWS:
        interpreter = arch_dir / "python.exe"
        script_dir = arch_dir / "Scripts"
        pip = script_dir / "pip.exe"
    else:
        interpreter = arch_dir / "bin" / "python"
        script_dir = arch_dir / "bin"
        pip = script_dir / "pip"
    script_dir.mkdir(parents=True, exist_ok=True)

    # A real interpreter is not needed: the validator only cares whether the
    # commands it runs succeed.
    interpreter.write_text(f"#!{sys.executable}\nimport sys\nsys.exit(0)\n")
    pip.write_text(f"#!{sys.executable}\nimport sys\nsys.exit(0)\n")
    for path in (interpreter, pip):
        path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    (toolcache_root / "Python" / version / f"{arch}.complete").touch()
    return arch_dir


class ToolcacheTestCase(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self.toolcache_root = Path(self._temp_dir.name)

    def complete_marker(self, arch_dir: Path) -> Path:
        return arch_dir.parent / f"{arch_dir.name}.complete"


class TestGetToolcacheRoot(ToolcacheTestCase):
    def test_prefers_agent_toolsdirectory(self):
        with mock.patch.dict(
            os.environ,
            {"AGENT_TOOLSDIRECTORY": "/agent", "RUNNER_TOOL_CACHE": "/runner"},
        ):
            self.assertEqual(get_toolcache_root(), Path("/agent"))

    def test_falls_back_to_runner_tool_cache(self):
        with mock.patch.dict(os.environ, {"RUNNER_TOOL_CACHE": "/runner"}, clear=True):
            self.assertEqual(get_toolcache_root(), Path("/runner"))

    def test_returns_none_when_unset(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(get_toolcache_root())


class TestFindEntries(ToolcacheTestCase):
    def test_matches_patch_versions_of_requested_version(self):
        make_entry(self.toolcache_root, "3.12.12")
        make_entry(self.toolcache_root, "3.12.14")
        make_entry(self.toolcache_root, "3.11.9")

        found = find_entries(self.toolcache_root, "3.12")

        self.assertEqual([entry.parent.name for entry in found], ["3.12.12", "3.12.14"])

    def test_does_not_match_unrelated_prefix(self):
        # "3.1" must not select "3.12.12".
        make_entry(self.toolcache_root, "3.12.12")
        self.assertEqual(find_entries(self.toolcache_root, "3.1"), [])

    def test_returns_empty_without_python_toolcache(self):
        self.assertEqual(find_entries(self.toolcache_root, "3.12"), [])


class TestValidateEntry(ToolcacheTestCase):
    def test_usable_entry_reports_no_error(self):
        arch_dir = make_entry(self.toolcache_root, "3.12.12")
        self.assertIsNone(validate_entry(arch_dir))

    def test_missing_interpreter_is_reported(self):
        arch_dir = make_entry(self.toolcache_root, "3.12.12")
        clean_python_toolcache.get_interpreter_path(arch_dir).unlink()

        error = validate_entry(arch_dir)

        self.assertIsNotNone(error)
        self.assertIn("does not exist", error)

    def test_failing_interpreter_is_reported(self):
        arch_dir = make_entry(self.toolcache_root, "3.12.12")
        interpreter = clean_python_toolcache.get_interpreter_path(arch_dir)
        interpreter.write_text(f"#!{sys.executable}\nimport sys\nsys.exit(1)\n")
        interpreter.chmod(interpreter.stat().st_mode | stat.S_IEXEC)

        error = validate_entry(arch_dir)

        self.assertIsNotNone(error)
        self.assertIn("exited with 1", error)

    @unittest.skipIf(IS_WINDOWS, "shebangs are POSIX only")
    def test_console_script_with_dangling_shebang_is_reported(self):
        # The reported failure: the interpreter works but pip's shebang points
        # at a path that no longer exists, which bash reports as exit 127.
        arch_dir = make_entry(self.toolcache_root, "3.12.12")
        pip = arch_dir / "bin" / "pip"
        pip.write_text(f"#!{arch_dir}/bin/deleted-python\n")
        pip.chmod(pip.stat().st_mode | stat.S_IEXEC)

        error = validate_entry(arch_dir)

        self.assertIsNotNone(error)
        self.assertIn("pip", error)

    def test_puts_entry_lib_on_the_library_path(self):
        # actions/python-versions builds load the libpython inside their own
        # entry, so validating without this finds the system Python instead.
        arch_dir = make_entry(self.toolcache_root, "3.12.12")
        library_path_var = clean_python_toolcache._LIBRARY_PATH_VARS.get(sys.platform)
        if not library_path_var:
            self.skipTest("no library path variable on this platform")

        with mock.patch.object(
            clean_python_toolcache.subprocess, "run", autospec=True
        ) as run:
            run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
            validate_entry(arch_dir)

        env = run.call_args.kwargs["env"]
        self.assertIn(str(arch_dir / "lib"), env[library_path_var].split(os.pathsep))


class TestRemoveEntry(ToolcacheTestCase):
    def test_removes_directory_and_complete_marker(self):
        arch_dir = make_entry(self.toolcache_root, "3.12.12")

        remove_entry(arch_dir)

        self.assertFalse(arch_dir.exists())
        # setup-python only looks at the marker, so leaving it behind would
        # keep the deleted entry looking valid.
        self.assertFalse(self.complete_marker(arch_dir).exists())


class TestCleanToolcache(ToolcacheTestCase):
    def test_keeps_usable_entry(self):
        arch_dir = make_entry(self.toolcache_root, "3.12.12")

        self.assertEqual(clean_toolcache(self.toolcache_root, "3.12"), 0)

        self.assertTrue(arch_dir.exists())
        self.assertTrue(self.complete_marker(arch_dir).exists())

    def test_removes_unusable_entry(self):
        arch_dir = make_entry(self.toolcache_root, "3.12.12")
        clean_python_toolcache.get_interpreter_path(arch_dir).unlink()

        self.assertEqual(clean_toolcache(self.toolcache_root, "3.12"), 1)

        self.assertFalse(arch_dir.exists())
        self.assertFalse(self.complete_marker(arch_dir).exists())

    def test_leaves_other_versions_alone(self):
        broken = make_entry(self.toolcache_root, "3.12.12")
        other = make_entry(self.toolcache_root, "3.11.9")
        clean_python_toolcache.get_interpreter_path(broken).unlink()

        self.assertEqual(clean_toolcache(self.toolcache_root, "3.12"), 1)

        self.assertFalse(broken.exists())
        self.assertTrue(other.exists())

    def test_handles_missing_toolcache_root(self):
        self.assertEqual(clean_toolcache(None, "3.12"), 0)


if __name__ == "__main__":
    unittest.main()

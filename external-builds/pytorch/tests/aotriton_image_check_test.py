# Copyright Advanced Micro Devices, Inc.
# SPDX-License-Identifier: MIT

"""Tests for the AOTriton GPU image verification used by build_prod_wheels.py.

Regression coverage for ROCm/TheRock#7569, where a nightly torch wheel shipped an
AOTriton library containing only the gfx942/gfx950/gfx120x image sets. Fused
attention silently disappeared on gfx11xx and SDPA fell back to the math backend.
"""

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aotriton_image_check as checker

# Image set names appear inside the library as paths like
# "amd-gfx115x/flash/attn_fwd.zip".
COMPLETE_IMAGE_SETS = (
    "amd-gfx90a",
    "amd-gfx942",
    "amd-gfx950",
    "amd-gfx110x",
    "amd-gfx115x",
    "amd-gfx120x",
    "amd-gfx1250",
)
# What the bad ROCm/TheRock#7569 nightly actually shipped.
TRUNCATED_IMAGE_SETS = ("amd-gfx942", "amd-gfx950", "amd-gfx120x")
# AOTriton 0.11 grouped every gfx11xx target into a single image set.
LEGACY_IMAGE_SETS = (
    "amd-gfx90a",
    "amd-gfx942",
    "amd-gfx950",
    "amd-gfx11xx",
    "amd-gfx120x",
)

ALL_TARGETS = ["gfx90a", "gfx942", "gfx950", "gfx1100", "gfx1151", "gfx1201", "gfx1250"]


def _make_wheel(directory, name, image_sets, library_name="libaotriton_v2.so.0.13.0"):
    path = Path(directory) / name
    payload = b"".join(
        f"{image_set}/flash/attn_fwd.zip".encode() + b"\x00" for image_set in image_sets
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("torch/__init__.py", "")
        if library_name:
            zf.writestr(f"torch/lib/{library_name}", b"\x7fELF" + payload)
    return path


class ExpectedImageSetsTest(unittest.TestCase):
    def test_wildcard_mapping(self):
        self.assertEqual(checker.expected_image_sets("gfx1151")[0], "amd-gfx115x")
        self.assertEqual(checker.expected_image_sets("gfx1100")[0], "amd-gfx110x")
        self.assertEqual(checker.expected_image_sets("gfx1201")[0], "amd-gfx120x")

    def test_exact_names_win_over_wildcards(self):
        self.assertEqual(checker.expected_image_sets("gfx942")[0], "amd-gfx942")
        self.assertEqual(checker.expected_image_sets("gfx1250")[0], "amd-gfx1250")

    def test_legacy_grouped_set_also_covers_gfx11xx(self):
        self.assertIn("amd-gfx11xx", checker.expected_image_sets("gfx1151"))
        self.assertIn("amd-gfx11xx", checker.expected_image_sets("gfx1100"))

    def test_target_id_features_are_stripped(self):
        self.assertEqual(
            checker.expected_image_sets("gfx942:sramecc+:xnack-")[0], "amd-gfx942"
        )

    def test_unsupported_target(self):
        self.assertEqual(checker.expected_image_sets("gfx1030"), [])


class CheckWheelTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def test_complete_wheel_passes(self):
        wheel = _make_wheel(self.tmp, "torch-good.whl", COMPLETE_IMAGE_SETS)
        self.assertEqual(checker.check_wheel(wheel, ALL_TARGETS), [])

    def test_legacy_wheel_passes(self):
        wheel = _make_wheel(self.tmp, "torch-legacy.whl", LEGACY_IMAGE_SETS)
        self.assertEqual(
            checker.check_wheel(wheel, ["gfx1151", "gfx1100", "gfx942"]), []
        )

    def test_truncated_wheel_is_rejected(self):
        wheel = _make_wheel(self.tmp, "torch-bad.whl", TRUNCATED_IMAGE_SETS)
        problems = checker.check_wheel(wheel, ALL_TARGETS)
        self.assertEqual(len(problems), 4)
        self.assertTrue(any("gfx1151" in p for p in problems))
        self.assertTrue(any("gfx1100" in p for p in problems))
        self.assertTrue(any("gfx1250" in p for p in problems))
        self.assertTrue(any("gfx90a" in p for p in problems))

    def test_truncated_wheel_passes_for_covered_targets_only(self):
        wheel = _make_wheel(self.tmp, "torch-bad.whl", TRUNCATED_IMAGE_SETS)
        self.assertEqual(checker.check_wheel(wheel, ["gfx942", "gfx1201"]), [])

    def test_missing_library_is_rejected(self):
        wheel = _make_wheel(self.tmp, "torch-nolib.whl", (), library_name=None)
        problems = checker.check_wheel(wheel, ["gfx1151"])
        self.assertEqual(len(problems), 1)
        self.assertIn("no AOTriton library", problems[0])

    def test_uncovered_targets_are_skipped(self):
        wheel = _make_wheel(self.tmp, "torch-nolib.whl", (), library_name=None)
        self.assertEqual(checker.check_wheel(wheel, ["gfx1030"]), [])

    def test_main_exit_codes(self):
        good = _make_wheel(self.tmp, "torch-good.whl", COMPLETE_IMAGE_SETS)
        bad = _make_wheel(self.tmp, "torch-bad.whl", TRUNCATED_IMAGE_SETS)
        self.assertEqual(checker.main([str(good), "--gfx-archs", "gfx1151;gfx942"]), 0)
        self.assertEqual(checker.main([str(bad), "--gfx-archs", "gfx1151;gfx942"]), 1)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python
# Copyright Advanced Micro Devices, Inc.
# SPDX-License-Identifier: MIT

"""Verifies that a built torch wheel ships AOTriton kernel images for every
requested GPU target.

AOTriton embeds one image set per GPU target inside libaotriton_v2.so, named
after the wildcard patterns in pytorch/cmake/External/aotriton.cmake (gfx1151 ->
amd-gfx115x). When a build emits fewer image sets than requested, nothing fails:
the arch is still reported as supported by AOTriton's own gating, so SDPA merely
warns and falls back to the math backend, which is O(seq_len^2) in memory and
makes long-sequence workloads unusable. See ROCm/TheRock#7569.
"""

import argparse
import re
import sys
import zipfile
from pathlib import Path

# Mirrors __AOTRITON_IMAGE_LIST in pytorch/cmake/External/aotriton.cmake, where
# 'x' is a single-character wildcard matched against the gfx target. The naming
# varies across AOTriton releases (0.11 grouped all of gfx11xx into one set), so
# a target counts as covered by any matching set.
AOTRITON_IMAGE_SETS = (
    "amd-gfx90a",
    "amd-gfx942",
    "amd-gfx950",
    "amd-gfx110x",
    "amd-gfx115x",
    "amd-gfx11xx",
    "amd-gfx120x",
    "amd-gfx1250",
)

_IMAGE_SET_RE = re.compile(rb"amd-gfx[0-9a-z]+")


def expected_image_sets(gfx_arch: str) -> list[str]:
    """Returns the image sets that would cover `gfx_arch`, most specific first."""
    # Strip target-ID features such as gfx942:sramecc+:xnack-.
    gfx_arch = gfx_arch.split(":")[0].strip()
    if not gfx_arch:
        return []
    matches = [
        image_set
        for image_set in AOTRITON_IMAGE_SETS
        if re.fullmatch(image_set[len("amd-") :].replace("x", "."), gfx_arch)
    ]
    return sorted(matches, key=lambda image_set: image_set.count("x"))


def find_image_sets(library_bytes: bytes) -> set[str]:
    return {match.decode() for match in _IMAGE_SET_RE.findall(library_bytes)}


def read_aotriton_library(wheel: Path) -> tuple[str, bytes] | None:
    with zipfile.ZipFile(wheel) as zf:
        for name in zf.namelist():
            base = name.rsplit("/", 1)[-1]
            if base.startswith(("libaotriton_v2.so", "aotriton_v2.dll")):
                return name, zf.read(name)
    return None


def check_wheel(wheel: Path, gfx_archs: list[str]) -> list[str]:
    """Returns a list of human-readable problems, empty when the wheel is good."""
    covered = {arch: expected_image_sets(arch) for arch in gfx_archs}
    covered = {arch: sets for arch, sets in covered.items() if sets}

    if not covered:
        print(
            f"No requested target is covered by AOTriton ({', '.join(gfx_archs)}); "
            "skipping image check."
        )
        return []

    found = read_aotriton_library(wheel)
    if found is None:
        return [
            f"{wheel.name} contains no AOTriton library, but fused attention was "
            f"requested for: {', '.join(sorted(covered))}"
        ]

    library_name, library_bytes = found
    present = find_image_sets(library_bytes)
    print(
        f"{wheel.name}: {library_name} ({len(library_bytes)} bytes) provides "
        f"[{', '.join(sorted(present)) or 'none'}]"
    )
    return [
        f"{library_name} has no AOTriton images for {gfx_arch} "
        f"(expected one of: {', '.join(sets)})"
        for gfx_arch, sets in sorted(covered.items())
        if not present.intersection(sets)
    ]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("wheel", type=Path, help="Built torch wheel to verify")
    p.add_argument(
        "--gfx-archs",
        required=True,
        help="Requested GPU targets, separated by ';' or ','",
    )
    args = p.parse_args(argv)

    gfx_archs = [arch for arch in re.split(r"[;,]", args.gfx_archs) if arch.strip()]
    problems = check_wheel(args.wheel, gfx_archs)
    for problem in problems:
        print(f"ERROR: {problem}", file=sys.stderr)
    if problems:
        print(
            "ERROR: the AOTriton build did not produce images for every requested "
            "target. Shipping this wheel would silently disable flash and "
            "memory-efficient attention on those targets (ROCm/TheRock#7569).",
            file=sys.stderr,
        )
        return 1
    print("AOTriton image sets present for all requested targets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

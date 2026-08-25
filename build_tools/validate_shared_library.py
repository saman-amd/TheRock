#!/usr/bin/env python
# Copyright Advanced Micro Devices, Inc.
# SPDX-License-Identifier: MIT

"""Validates that a shared library can be loaded."""

import argparse
import contextlib
import ctypes
import os
import sys


def run(args: argparse.Namespace):
    with contextlib.ExitStack() as stack:
        # Windows has no RPATH: dependent DLLs are resolved with the default
        # search order, which does not include the directory of a library that
        # is loaded by absolute path.
        if hasattr(os, "add_dll_directory"):
            for dep_dir in args.dep_dir:
                stack.enter_context(os.add_dll_directory(dep_dir))

        for shared_lib in args.shared_libs:
            print(f"Validating shared library: {shared_lib}", end="")
            so = ctypes.cdll.LoadLibrary(shared_lib)
            print(" :", so)


def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument("shared_libs", nargs="*", help="Shared libraries to validate")
    p.add_argument(
        "--dep-dir",
        action="append",
        default=[],
        help="Directory to search for dependent libraries (Windows only)",
    )
    args = p.parse_args(argv)
    run(args)


if __name__ == "__main__":
    main(sys.argv[1:])

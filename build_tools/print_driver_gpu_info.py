#!/usr/bin/env python3
# Copyright Advanced Micro Devices, Inc.
# SPDX-License-Identifier: MIT

"""
Sanity check script for CI runners.

On Linux:
  - run "amd-smi static"
  - run "rocminfo"

On Windows:
  - run "hipInfo.exe"

Besides printing raw command output, this verifies that at least one GPU agent
is actually enumerated, so that a runner whose GPUs are not reachable through
the HSA/KFD stack fails here instead of much later inside a test.
"""

import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
from typing import List, Optional


def log(*args, **kwargs):
    print(*args, **kwargs)
    sys.stdout.flush()


def run_command(args: List[str | Path], cwd: Optional[Path] = None) -> Optional[str]:
    args = [str(arg) for arg in args]
    if cwd is None:
        cwd = Path.cwd()

    log(f"++ Exec [{cwd}]$ {shlex.join(args)}")

    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=True,
            stdin=subprocess.DEVNULL,
        )
        log(proc.stdout.rstrip())
        return proc.stdout
    except FileNotFoundError:
        log(f"{args[0]}: command not found")
        return None


def run_command_with_search(
    label: str,
    command: str,
    args: List[str],
    extra_command_search_paths: List[Path],
) -> Optional[str]:
    """
    Run a command, searching in extra paths first, then PATH.

    Example:
        run_command_with_search(
            label="amd-smi static",
            command="amd-smi",
            args=["static"],
            extra_command_search_paths=[bin_dir],
        )
    """
    # Try explicit directories first (e.g. THEROCK_DIR/build/bin)
    for base in extra_command_search_paths:
        candidate = base / command
        if candidate.exists():
            log(f"\n=== {label} ===")
            return run_command([candidate] + args)

    # Then fall back to PATH
    resolved = shutil.which(command)
    if resolved:
        log(f"\n=== {label} ===")
        return run_command([resolved] + args)

    # Nothing found
    log(f"\n=== {label} ===")
    log(f"{command}: command not found")
    return None


# Set by the runner controller to isolate a job to a subset of GPUs. A stale or
# out-of-range ordinal here leaves the runtime with no agents at all.
DEVICE_VISIBILITY_ENV_VARS = [
    "ROCR_VISIBLE_DEVICES",
    "HIP_VISIBLE_DEVICES",
    "CUDA_VISIBLE_DEVICES",
    "GPU_DEVICE_ORDINAL",
]


def log_device_visibility_env() -> None:
    log("\n=== Device visibility environment ===")
    for name in DEVICE_VISIBILITY_ENV_VARS:
        log(f"{name}={os.getenv(name, '<unset>')}")


def count_gpu_agents(rocminfo_output: Optional[str]) -> Optional[int]:
    """
    Count GPU agents in "rocminfo" output.

    Returns None if the output is unusable, so that a missing or broken rocminfo
    is not misreported as "zero GPUs".
    """
    if not rocminfo_output:
        return None
    agents = re.findall(r"^\s*Device\s+Type:\s*(\S+)", rocminfo_output, re.MULTILINE)
    if not agents:
        return None
    return sum(1 for agent in agents if agent.upper() == "GPU")


def run_sanity(os_name: str) -> int:
    THIS_SCRIPT_DIR = Path(__file__).resolve().parent
    THEROCK_DIR = THIS_SCRIPT_DIR.parent
    bin_dir = Path(os.getenv("THEROCK_BIN_DIR", THEROCK_DIR / "build" / "bin"))

    log("=== Sanity check: driver / GPU info ===")
    log_device_visibility_env()

    if os_name.lower() == "windows":
        # Windows: only hipInfo.exe
        run_command_with_search(
            label="hipInfo.exe",
            command="hipInfo.exe",
            args=[],
            extra_command_search_paths=[bin_dir],
        )
        log("\n=== End of sanity check ===")
        return 0
    else:
        # Linux: amd-smi static + rocminfo
        run_command_with_search(
            label="amd-smi static",
            command="amd-smi",
            args=["static"],
            extra_command_search_paths=[bin_dir],
        )
        rocminfo_output = run_command_with_search(
            label="rocminfo",
            command="rocminfo",
            args=[],
            extra_command_search_paths=[bin_dir],
        )
        run_command_with_search(
            label="Kernel version",
            command="uname",
            args=["-r"],
            extra_command_search_paths=[bin_dir],
        )

    # "rocminfo" exits 0 even when it enumerates no GPU agents, so check the
    # agent count explicitly rather than trusting the exit code.
    gpu_agent_count = count_gpu_agents(rocminfo_output)
    log("\n=== GPU agent check ===")
    if gpu_agent_count is None:
        log("rocminfo did not report any agents; cannot verify GPU availability")
        log("\n=== End of sanity check ===")
        return 1
    log(f"GPU agents enumerated by rocminfo: {gpu_agent_count}")
    if gpu_agent_count == 0:
        log(
            "ERROR: no GPU agents are visible to the HSA/KFD stack on this runner.\n"
            "Tests requiring a GPU cannot run. Common causes:\n"
            "  * a device visibility variable listed above names a device ordinal\n"
            "    that does not exist inside the container\n"
            "  * /dev/kfd or /dev/dri is not mapped into the container\n"
            "  * the amdgpu driver is unhealthy on this machine"
        )
        log("\n=== End of sanity check ===")
        return 1

    log("\n=== End of sanity check ===")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    detected = platform.system()
    return run_sanity(detected)


if __name__ == "__main__":
    sys.exit(main())

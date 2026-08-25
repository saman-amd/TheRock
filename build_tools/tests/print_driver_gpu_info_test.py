# Copyright Advanced Micro Devices, Inc.
# SPDX-License-Identifier: MIT

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import print_driver_gpu_info


ROCMINFO_ONE_GPU = """
ROCk module is loaded
=====================
HSA Agents
==========
*******
Agent 1
*******
  Name:                    Intel(R) Xeon(R) w7-3455
  Device Type:             CPU
*******
Agent 2
*******
  Name:                    gfx1100
  Marketing Name:          AMD Radeon RX 7900 XTX
  Device Type:             GPU
*** Done ***
"""

# What rocminfo prints when ROCR_VISIBLE_DEVICES names an ordinal that does not
# exist: it still exits 0, but no GPU agent is listed.
ROCMINFO_NO_GPU = """
ROCk module is loaded
=====================
HSA Agents
==========
*******
Agent 1
*******
  Name:                    Intel(R) Xeon(R) w7-3455
  Device Type:             CPU
  ISA Info:
*** Done ***
"""


class CountGpuAgentsTest(unittest.TestCase):
    def test_counts_single_gpu(self):
        self.assertEqual(print_driver_gpu_info.count_gpu_agents(ROCMINFO_ONE_GPU), 1)

    def test_counts_multiple_gpus(self):
        output = ROCMINFO_ONE_GPU + "  Device Type:             GPU\n"
        self.assertEqual(print_driver_gpu_info.count_gpu_agents(output), 2)

    def test_cpu_only_output_counts_zero(self):
        self.assertEqual(print_driver_gpu_info.count_gpu_agents(ROCMINFO_NO_GPU), 0)

    def test_missing_output_is_indeterminate(self):
        self.assertIsNone(print_driver_gpu_info.count_gpu_agents(None))
        self.assertIsNone(print_driver_gpu_info.count_gpu_agents(""))

    def test_output_without_agents_is_indeterminate(self):
        self.assertIsNone(print_driver_gpu_info.count_gpu_agents("some junk"))


class RunSanityTest(unittest.TestCase):
    def _run_linux_sanity(self, rocminfo_output):
        def fake_run(label, command, args, extra_command_search_paths):
            if command == "rocminfo":
                return rocminfo_output
            return ""

        with patch.object(
            print_driver_gpu_info, "run_command_with_search", side_effect=fake_run
        ):
            return print_driver_gpu_info.run_sanity("Linux")

    def test_passes_when_a_gpu_is_enumerated(self):
        self.assertEqual(self._run_linux_sanity(ROCMINFO_ONE_GPU), 0)

    def test_fails_when_no_gpu_is_enumerated(self):
        """A runner with zero GPU agents must fail the sanity check."""
        self.assertEqual(self._run_linux_sanity(ROCMINFO_NO_GPU), 1)

    def test_fails_when_rocminfo_is_unavailable(self):
        self.assertEqual(self._run_linux_sanity(None), 1)

    def test_reports_device_visibility_env(self):
        with patch.dict(
            print_driver_gpu_info.os.environ, {"ROCR_VISIBLE_DEVICES": "1"}, clear=False
        ):
            with patch.object(print_driver_gpu_info, "log") as mock_log:
                print_driver_gpu_info.log_device_visibility_env()
        logged = "\n".join(str(call.args[0]) for call in mock_log.call_args_list)
        self.assertIn("ROCR_VISIBLE_DEVICES=1", logged)

    def test_main_propagates_failure(self):
        with patch.object(
            print_driver_gpu_info.platform, "system", return_value="Linux"
        ):
            with patch.object(print_driver_gpu_info, "run_sanity", return_value=1):
                self.assertEqual(print_driver_gpu_info.main([]), 1)


if __name__ == "__main__":
    unittest.main()

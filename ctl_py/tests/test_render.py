# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
# in compliance with the License. You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under the License
# is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
# or implied. See the License for the specific language governing permissions and limitations under
# the License.
"""Rendering tests: deterministic human tables and protobuf JSON."""

from __future__ import annotations

import json
import re

from google.protobuf.json_format import Parse

from storage_lender_ctl import render
from storage_lender_ctl.proto import ctl_pb2


def command_latency() -> ctl_pb2.GetCommandLatencyResponse:
    response = ctl_pb2.GetCommandLatencyResponse(
        capacity_per_command=256, process_started_unix_ms=1_700_000_000_123
    )
    response.commands.add(command="transfer_fd")
    response.commands.add(
        command="map_buffer",
        samples=12,
        errors=2,
        peak_in_flight=3,
        p50_us=10,
        p90_us=20,
        p99_us=30,
        max_us=40,
        event_loop_lag_p90_us=4,
        event_loop_lag_max_us=6,
        oldest_completed_unix_ms=1_700_000_001_001,
        newest_completed_unix_ms=1_700_000_002_002,
    )
    return response


def test_color_policy() -> None:
    assert not render.color_enabled("auto", False, "xterm", False)
    assert not render.color_enabled("auto", True, "dumb", False)
    assert not render.color_enabled("auto", True, "xterm", True)
    assert render.color_enabled("auto", True, "xterm", False)
    assert render.color_enabled("always", False, "dumb", True)
    assert not render.color_enabled("never", True, "xterm", False)


def test_style_only_wraps_when_enabled() -> None:
    assert render.style("x", render.ANSI_RED, False) == "x"
    assert render.style("x", render.ANSI_RED, True) == "\033[31mx\033[0m"


def test_format_unix_milliseconds() -> None:
    assert render.format_unix_milliseconds(1_700_000_000_123) == "2023-11-14T22:13:20.123Z"
    assert render.format_unix_milliseconds(0) == "1970-01-01T00:00:00.000Z"
    assert render.format_unix_milliseconds(2**63) == "-"


def test_render_table_aligns_first_column_left_and_others_right() -> None:
    output = render.render_table(("name", "n"), [("a", "1"), ("longer", "22")])
    assert output == "name     n\na        1\nlonger  22\n"


def test_latency_human_output_is_deterministic() -> None:
    output = render.render_latency_human(command_latency())

    assert output == render.render_latency_human(command_latency())
    assert output.startswith(
        "command latency\nprocess started: 2023-11-14T22:13:20.123Z\n"
        "window: last 256 per command\nunits: microseconds\n\n"
    )
    assert output.index("transfer_fd") < output.index("map_buffer")
    map_line = next(line for line in output.splitlines() if line.startswith("map_buffer"))
    assert re.fullmatch(
        r"map_buffer\s+12\s+2\s+3\s+10\s+20\s+30\s+40\s+4\s+6"
        r"\s+2023-11-14T22:13:21\.001Z\s+2023-11-14T22:13:22\.002Z",
        map_line,
    ), map_line
    assert "\033[" not in output


def test_absent_latency_values_render_as_dashes() -> None:
    output = render.render_latency_human(command_latency())
    empty_line = next(line for line in output.splitlines() if line.startswith("transfer_fd"))
    assert empty_line.count("-") == 8


def test_render_json_is_compact_protobuf_json() -> None:
    output = render.render_json(command_latency())

    assert output.endswith("\n")
    assert '"capacityPerCommand":256' in output
    assert '"processStartedUnixMs":"1700000000123"' in output
    assert "\033[" not in output
    parsed = Parse(output, ctl_pb2.GetCommandLatencyResponse())
    assert len(parsed.commands) == 2
    assert parsed.commands[1].p99_us == 30
    assert json.loads(output)["commands"][0] == {"command": "transfer_fd"}

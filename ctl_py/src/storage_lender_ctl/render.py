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
"""Human and JSON rendering of management responses."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone

from google.protobuf.json_format import MessageToDict
from google.protobuf.message import Message

from .proto import ctl_pb2

ANSI_RESET = "\033[0m"
ANSI_HEADING = "\033[1m"
ANSI_AMBER = "\033[33m"
ANSI_RED = "\033[31m"

COLUMN_GAP = "  "


def color_enabled(mode: str, stdout_is_tty: bool, term: str, no_color_set: bool) -> bool:
    """Apply the ``--color`` policy: ``auto`` needs a tty, a non-dumb TERM, and no NO_COLOR."""
    if mode == "always":
        return True
    if mode == "never":
        return False
    return stdout_is_tty and term != "dumb" and not no_color_set


def style(value: str, color: str, enabled: bool) -> str:
    """Wrap ``value`` in an ANSI color when ``enabled``; otherwise return it unchanged."""
    return f"{color}{value}{ANSI_RESET}" if enabled else value


def format_unix_milliseconds(value: int) -> str:
    """Render a Unix millisecond timestamp as UTC ISO-8601 with millisecond precision."""
    try:
        moment = datetime.fromtimestamp(value // 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return "-"
    return f"{moment.strftime('%Y-%m-%dT%H:%M:%S')}.{value % 1000:03d}Z"


def optional_number(message: Message, field: str) -> str:
    """Show an ``optional`` numeric field, or ``-`` when the server did not set it."""
    return str(getattr(message, field)) if message.HasField(field) else "-"


def render_table(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> str:
    """Lay out rows in fixed-width columns: first column left-aligned, the rest right-aligned."""
    materialized = [list(row) for row in rows]
    widths = [len(header) for header in headers]
    for row in materialized:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def layout(cells: Sequence[str]) -> str:
        return COLUMN_GAP.join(
            cell.ljust(widths[index]) if index == 0 else cell.rjust(widths[index])
            for index, cell in enumerate(cells)
        )

    lines = [layout(headers)]
    lines.extend(layout(row) for row in materialized)
    return "".join(f"{line}\n" for line in lines)


LATENCY_HEADERS = (
    "command",
    "samples",
    "errors",
    "peak",
    "p50",
    "p90",
    "p99",
    "max",
    "lag_p90",
    "lag_max",
    "oldest",
    "newest",
)


def _latency_row(summary: ctl_pb2.CommandLatencySummary) -> list[str]:
    def timestamp(field: str) -> str:
        return format_unix_milliseconds(getattr(summary, field)) if summary.HasField(field) else "-"

    return [
        summary.command,
        str(summary.samples),
        str(summary.errors),
        str(summary.peak_in_flight),
        optional_number(summary, "p50_us"),
        optional_number(summary, "p90_us"),
        optional_number(summary, "p99_us"),
        optional_number(summary, "max_us"),
        optional_number(summary, "event_loop_lag_p90_us"),
        optional_number(summary, "event_loop_lag_max_us"),
        timestamp("oldest_completed_unix_ms"),
        timestamp("newest_completed_unix_ms"),
    ]


def render_latency_human(response: ctl_pb2.GetCommandLatencyResponse) -> str:
    """Render the ``latency`` snapshot; the table has no semantic color, so none is applied."""
    header = (
        "command latency\n"
        f"process started: {format_unix_milliseconds(response.process_started_unix_ms)}\n"
        f"window: last {response.capacity_per_command} per command\n"
        "units: microseconds\n\n"
    )
    return header + render_table(
        LATENCY_HEADERS, (_latency_row(summary) for summary in response.commands)
    )


def render_json(message: Message) -> str:
    """Compact protobuf JSON (camelCase names, 64-bit integers as strings), newline-terminated."""
    return json.dumps(MessageToDict(message), separators=(",", ":")) + "\n"

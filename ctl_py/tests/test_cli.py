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
"""Command-line behaviour: option placement, exit statuses, and error reporting."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from conftest import FakeServer

from storage_lender_ctl import __version__, cli
from storage_lender_ctl.proto import ctl_pb2, wire_pb2


def parse(*argv: str) -> cli.Options:
    namespace = cli.build_parser().parse_args(argv)
    return cli._options_from(namespace)


def test_defaults() -> None:
    options = parse("quota")
    assert options == cli.Options()
    assert options.socket_path == "/run/storage-lender/ctl.sock"


def test_options_accepted_before_or_after_the_command() -> None:
    before = parse("--format", "json", "-s", "/run/custom.sock", "latency")
    after = parse("latency", "--format", "json", "-s", "/run/custom.sock", "--color", "never")
    assert before == cli.Options(socket_path="/run/custom.sock", output_format="json")
    assert after == cli.Options(socket_path="/run/custom.sock", output_format="json", color="never")


def test_value_before_the_command_survives_the_subparser() -> None:
    assert parse("-c", "always", "latency").color == "always"


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--format", "yaml", "latency"], "unknown format: yaml"),
        (["latency", "--color", "sometimes"], "unknown color mode: sometimes"),
        (["latency", "--socket", ""], "socket path must not be empty"),
        ([], "the following arguments are required: COMMAND"),
        (["sessions"], "invalid choice: 'sessions'"),
        (["latency", "extra"], "unrecognized arguments: extra"),
    ],
)
def test_usage_errors_exit_2_without_connecting(capsys, argv: list[str], message: str) -> None:
    assert cli.main(argv) == cli.EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert message in captured.err
    assert captured.err.startswith("usage: storage-lender-ctl")


def test_help_and_version_exit_0(capsys) -> None:
    assert cli.main(["--help"]) == cli.EXIT_OK
    help_text = capsys.readouterr().out
    assert "quota" in help_text
    assert "latency" in help_text
    assert cli.main(["--version"]) == cli.EXIT_OK
    assert capsys.readouterr().out == f"storage-lender-ctl {__version__}\n"


def test_quota_renders_human_output(capsys, fake_server: FakeServer) -> None:
    quota = ctl_pb2.GetQuotaStateResponse(generation=1, mode=ctl_pb2.QUOTA_MODE_UNLIMITED)
    fake_server.respond_with(
        wire_pb2.Response(status_code=wire_pb2.OK, payload=quota.SerializeToString())
    )

    assert (
        cli.main(["--socket", fake_server.socket_path, "--color", "never", "quota"]) == cli.EXIT_OK
    )

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.startswith("quota state\ngeneration: 1\nmode: unlimited\n")
    assert "\nglobal\n" in captured.out


def test_latency_renders_human_output(capsys, fake_server: FakeServer) -> None:
    latency = ctl_pb2.GetCommandLatencyResponse(capacity_per_command=256)
    latency.commands.add(command="get_device_info", samples=1, errors=1)
    fake_server.respond_with(
        wire_pb2.Response(status_code=wire_pb2.OK, payload=latency.SerializeToString())
    )

    assert cli.main(["--socket", fake_server.socket_path, "latency"]) == cli.EXIT_OK

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.startswith("command latency\n")
    assert "get_device_info" in captured.out


def test_latency_renders_json_output(capsys, fake_server: FakeServer) -> None:
    latency = ctl_pb2.GetCommandLatencyResponse(capacity_per_command=256)
    fake_server.respond_with(
        wire_pb2.Response(status_code=wire_pb2.OK, payload=latency.SerializeToString())
    )

    assert cli.main(["-s", fake_server.socket_path, "-f", "json", "latency"]) == cli.EXIT_OK

    assert capsys.readouterr().out == '{"capacityPerCommand":256}\n'


def test_missing_socket_exits_1_with_reason(capsys, tmp_path) -> None:
    missing = str(tmp_path / "missing.sock")

    assert cli.main(["--socket", missing, "latency"]) == cli.EXIT_FAILURE

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "storage-lender-ctl: failed to connect to ctl socket: No such file or directory\n"
    )


def test_server_status_exits_1_with_reason(capsys, fake_server: FakeServer) -> None:
    fake_server.respond_with(
        wire_pb2.Response(status_code=wire_pb2.PERMISSION_DENIED, error_message="root required")
    )

    assert cli.main(["-s", fake_server.socket_path, "latency"]) == cli.EXIT_FAILURE

    assert capsys.readouterr().err == (
        "storage-lender-ctl: server returned status PERMISSION_DENIED (7): root required\n"
    )


@pytest.mark.skipif(
    "STORAGE_LENDER_CTL_LAUNCHER" not in os.environ, reason="build-tree launcher path not provided"
)
def test_launcher_script_runs_the_package() -> None:
    result = subprocess.run(
        [os.environ["STORAGE_LENDER_CTL_LAUNCHER"], "--version"],
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": os.environ.get("PATH", "")},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"storage-lender-ctl {__version__}\n"


def test_module_entry_point_runs() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "storage_lender_ctl", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("storage-lender-ctl ")

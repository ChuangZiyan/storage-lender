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
"""Transport tests against the fake server."""

from __future__ import annotations

import errno
import struct

import pytest
from conftest import FakeServer

from storage_lender_ctl import client
from storage_lender_ctl.proto import ctl_pb2, wire_pb2


def ok_response(payload: bytes) -> wire_pb2.Response:
    return wire_pb2.Response(status_code=wire_pb2.OK, payload=payload)


def test_latency_call_sends_empty_request_and_parses_response(fake_server: FakeServer) -> None:
    latency = ctl_pb2.GetCommandLatencyResponse(capacity_per_command=256)
    fake_server.respond_with(ok_response(latency.SerializeToString()))

    response = client.get_command_latency(fake_server.socket_path)

    assert response.capacity_per_command == 256
    assert len(fake_server.requests) == 1
    assert fake_server.requests[0].method == ctl_pb2.GET_COMMAND_LATENCY
    assert fake_server.requests[0].payload == b""


def test_quota_call_sends_empty_request_and_parses_response(fake_server: FakeServer) -> None:
    quota = ctl_pb2.GetQuotaStateResponse(generation=42)
    fake_server.respond_with(ok_response(quota.SerializeToString()))

    response = client.get_quota_state(fake_server.socket_path)

    assert response.generation == 42
    assert fake_server.requests[0].method == ctl_pb2.GET_QUOTA_STATE
    assert fake_server.requests[0].payload == b""


def test_unparseable_quota_payload_names_the_command(fake_server: FakeServer) -> None:
    fake_server.respond_with(ok_response(b"\xff\xff\xff\xff\xff"))

    with pytest.raises(client.CtlProtocolError, match="failed to parse quota response"):
        client.get_quota_state(fake_server.socket_path)


def test_server_status_is_reported_with_its_message(fake_server: FakeServer) -> None:
    fake_server.respond_with(
        wire_pb2.Response(status_code=wire_pb2.PERMISSION_DENIED, error_message="root required")
    )

    with pytest.raises(client.CtlServerError) as failure:
        client.get_command_latency(fake_server.socket_path)

    assert failure.value.status_code == wire_pb2.PERMISSION_DENIED
    assert failure.value.message == "root required"
    assert str(failure.value) == "server returned status PERMISSION_DENIED (7): root required"


def test_unparseable_envelope_is_a_protocol_error(fake_server: FakeServer) -> None:
    garbage = b"\xff\xff\xff\xff\xff"
    fake_server.respond_with_raw(struct.pack("<I", len(garbage)) + garbage)

    with pytest.raises(client.CtlProtocolError, match="failed to parse response envelope"):
        client.get_command_latency(fake_server.socket_path)


def test_unparseable_payload_names_the_command(fake_server: FakeServer) -> None:
    fake_server.respond_with(ok_response(b"\xff\xff\xff\xff\xff"))

    with pytest.raises(client.CtlProtocolError, match="failed to parse command latency response"):
        client.get_command_latency(fake_server.socket_path)


def test_oversized_response_frame_is_rejected_before_reading_it(fake_server: FakeServer) -> None:
    fake_server.respond_with_raw(struct.pack("<I", client.MAX_FRAME_BYTES + 1))

    with pytest.raises(client.CtlProtocolError, match="response frame exceeds the maximum size"):
        client.get_command_latency(fake_server.socket_path)


def test_closed_connection_is_an_io_error(fake_server: FakeServer) -> None:
    fake_server.respond_with_raw(b"\x10")

    with pytest.raises(client.CtlIoError, match="connection closed by server"):
        client.get_command_latency(fake_server.socket_path)


def test_missing_socket_reports_errno(tmp_path) -> None:
    with pytest.raises(client.CtlIoError) as failure:
        client.get_command_latency(str(tmp_path / "missing.sock"))

    assert failure.value.errno_value == errno.ENOENT
    assert str(failure.value) == "failed to connect to ctl socket: No such file or directory"


def test_overlong_socket_path_is_rejected_without_connecting() -> None:
    with pytest.raises(client.CtlIoError) as failure:
        client.call("/" + "x" * client.SUN_PATH_MAX, ctl_pb2.GET_COMMAND_LATENCY)

    assert failure.value.errno_value == errno.ENAMETOOLONG


def test_encode_frame_caps_request_size() -> None:
    assert client.encode_frame(b"abc") == b"\x03\x00\x00\x00abc"
    with pytest.raises(client.CtlProtocolError, match="request frame exceeds the maximum size"):
        client.encode_frame(b"x" * (client.MAX_FRAME_BYTES + 1))

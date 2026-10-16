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
"""Shared fixtures: a one-shot fake management server on a temporary Unix socket."""

from __future__ import annotations

import socket
import struct
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from storage_lender_ctl.proto import wire_pb2

FRAME_HEADER = struct.Struct("<I")


def _recv_exact(connection: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = connection.recv(size - len(data))
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)


@dataclass
class FakeServer:
    """Accepts one connection, records the request, and answers with ``reply`` verbatim."""

    socket_path: str
    reply: bytes = b""
    requests: list[wire_pb2.Request] = field(default_factory=list)
    _listener: socket.socket | None = None
    _thread: threading.Thread | None = None

    def respond_with(self, response: wire_pb2.Response) -> None:
        self.respond_with_raw(FRAME_HEADER.pack(response.ByteSize()) + response.SerializeToString())

    def respond_with_raw(self, framed_reply: bytes) -> None:
        self.reply = framed_reply
        self._listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._listener.bind(self.socket_path)
        self._listener.listen(1)
        self._thread = threading.Thread(target=self._serve_once, daemon=True)
        self._thread.start()

    def _serve_once(self) -> None:
        assert self._listener is not None
        connection, _ = self._listener.accept()
        with connection:
            (size,) = FRAME_HEADER.unpack(_recv_exact(connection, FRAME_HEADER.size))
            request = wire_pb2.Request()
            request.ParseFromString(_recv_exact(connection, size))
            self.requests.append(request)
            connection.sendall(self.reply)

    def close(self) -> None:
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self._listener is not None:
            self._listener.close()


@pytest.fixture
def fake_server(tmp_path: Path) -> Iterator[FakeServer]:
    server = FakeServer(str(tmp_path / "ctl.sock"))
    yield server
    server.close()

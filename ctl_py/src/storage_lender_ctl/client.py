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
"""Transport for the management protocol.

One request per connection: a 4-byte little-endian length prefix followed by a serialized
``wire.Request`` envelope, answered by one framed ``wire.Response``. Frames are capped at 64 KiB in
both directions, matching ``storage_lender::wire::MAX_FRAME_BYTES`` on the server.
"""

from __future__ import annotations

import errno
import os
import socket
import struct
from typing import TypeVar

from google.protobuf.message import DecodeError, Message

from .proto import ctl_pb2, wire_pb2

MAX_FRAME_BYTES = 64 * 1024
FRAME_HEADER = struct.Struct("<I")
SUN_PATH_MAX = 108

MessageType = TypeVar("MessageType", bound=Message)


class CtlError(Exception):
    """Base class for every failure the CLI reports as exit status 1."""


class CtlIoError(CtlError):
    """Socket or filesystem failure while talking to the server."""

    def __init__(self, message: str, errno_value: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.errno_value = errno_value

    def __str__(self) -> str:
        if self.errno_value:
            return f"{self.message}: {os.strerror(self.errno_value)}"
        return self.message


class CtlServerError(CtlError):
    """The server answered with a non-OK status code."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message

    def __str__(self) -> str:
        name = (
            wire_pb2.StatusCode.Name(self.status_code)
            if self.status_code in wire_pb2.StatusCode.values()
            else "UNKNOWN"
        )
        text = f"server returned status {name} ({self.status_code})"
        return f"{text}: {self.message}" if self.message else text


class CtlProtocolError(CtlError):
    """The server sent something that is not a valid framed response."""


def encode_frame(payload: bytes) -> bytes:
    """Prefix ``payload`` with its little-endian length, rejecting oversized frames."""
    if len(payload) > MAX_FRAME_BYTES:
        raise CtlProtocolError("request frame exceeds the maximum size")
    return FRAME_HEADER.pack(len(payload)) + payload


def _read_exact(sock: socket.socket, size: int, what: str) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        try:
            chunk = sock.recv(size - len(chunks))
        except OSError as error:
            raise CtlIoError(f"failed to read {what}", error.errno) from error
        if not chunk:
            raise CtlIoError(f"failed to read {what}: connection closed by server")
        chunks.extend(chunk)
    return bytes(chunks)


def call(socket_path: str, method: int, payload: bytes = b"") -> bytes:
    """Send one request and return the response payload, raising :class:`CtlError` on failure."""
    if len(socket_path.encode()) >= SUN_PATH_MAX:
        raise CtlIoError("socket path exceeds sockaddr_un::sun_path", errno.ENAMETOOLONG)

    request = wire_pb2.Request(method=method, payload=payload)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        try:
            sock.connect(socket_path)
        except OSError as error:
            raise CtlIoError("failed to connect to ctl socket", error.errno) from error
        try:
            sock.sendall(encode_frame(request.SerializeToString()))
        except OSError as error:
            raise CtlIoError("failed to write ctl request", error.errno) from error

        (payload_size,) = FRAME_HEADER.unpack(
            _read_exact(sock, FRAME_HEADER.size, "response frame header")
        )
        if payload_size > MAX_FRAME_BYTES:
            raise CtlProtocolError("response frame exceeds the maximum size")
        raw_response = (
            _read_exact(sock, payload_size, "response frame payload") if payload_size else b""
        )

    response = wire_pb2.Response()
    try:
        response.ParseFromString(raw_response)
    except DecodeError as error:
        raise CtlProtocolError("failed to parse response envelope") from error
    if response.status_code != wire_pb2.OK:
        raise CtlServerError(response.status_code, response.error_message)
    return response.payload


def _parse(message_type: type[MessageType], payload: bytes, what: str) -> MessageType:
    message = message_type()
    try:
        message.ParseFromString(payload)
    except DecodeError as error:
        raise CtlProtocolError(f"failed to parse {what} response") from error
    return message


def get_command_latency(socket_path: str) -> ctl_pb2.GetCommandLatencyResponse:
    """Fetch the process-wide API command latency snapshot."""
    payload = call(socket_path, ctl_pb2.GET_COMMAND_LATENCY)
    return _parse(ctl_pb2.GetCommandLatencyResponse, payload, "command latency")

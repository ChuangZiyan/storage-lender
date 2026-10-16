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
"""Command-line front end: argument parsing, dispatch, and error reporting."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, fields

from google.protobuf.message import Message

from . import __version__, client, render

PROG = "storage-lender-ctl"
DEFAULT_CTL_SOCKET = "/run/storage-lender/ctl.sock"
OUTPUT_FORMATS = ("human", "json")
COLOR_MODES = ("auto", "always", "never")

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2


@dataclass(frozen=True)
class Options:
    """Options shared by every subcommand; they may appear before or after the command."""

    socket_path: str = DEFAULT_CTL_SOCKET
    output_format: str = "human"
    color: str = "auto"


@dataclass(frozen=True)
class Command:
    """One subcommand: how to fetch its response and how to show it to a human."""

    name: str
    help: str
    fetch: Callable[[str], Message]
    render_human: Callable[[Message, bool], str]


COMMANDS: tuple[Command, ...] = (
    Command(
        name="latency",
        help="show API command latency and event-loop lag for this daemon process",
        fetch=client.get_command_latency,
        render_human=lambda response, _color: render.render_latency_human(response),
    ),
)


def _choice(name: str, choices: Sequence[str]) -> Callable[[str], str]:
    def parse(value: str) -> str:
        if value not in choices:
            raise argparse.ArgumentTypeError(f"unknown {name}: {value}")
        return value

    return parse


def _socket_path(value: str) -> str:
    if not value:
        raise argparse.ArgumentTypeError("socket path must not be empty")
    return value


def _common_options() -> argparse.ArgumentParser:
    # SUPPRESS keeps a subparser from overwriting a value given before the command name;
    # Options() supplies the defaults afterwards.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-s",
        "--socket",
        dest="socket_path",
        metavar="PATH",
        type=_socket_path,
        default=argparse.SUPPRESS,
        help=f"management socket path (default: {DEFAULT_CTL_SOCKET})",
    )
    common.add_argument(
        "-f",
        "--format",
        dest="output_format",
        metavar="FORMAT",
        type=_choice("format", OUTPUT_FORMATS),
        default=argparse.SUPPRESS,
        help="output format: human or json (default: human)",
    )
    common.add_argument(
        "-c",
        "--color",
        dest="color",
        metavar="MODE",
        type=_choice("color mode", COLOR_MODES),
        default=argparse.SUPPRESS,
        help="color mode: auto, always, or never (default: auto)",
    )
    return common


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser; exposed for tests and shell-completion generators."""
    common = _common_options()
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Management client for storage-lender-server.",
        parents=[common],
    )
    parser.add_argument("-V", "--version", action="version", version=f"{PROG} {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
    for command in COMMANDS:
        subparser = subparsers.add_parser(command.name, help=command.help, parents=[common])
        subparser.set_defaults(handler=command)
    return parser


def _options_from(namespace: argparse.Namespace) -> Options:
    given = {
        field.name: getattr(namespace, field.name)
        for field in fields(Options)
        if hasattr(namespace, field.name)
    }
    return Options(**given)


def _render(command: Command, options: Options, response: Message) -> str:
    if options.output_format == "json":
        return render.render_json(response)
    color = render.color_enabled(
        options.color,
        sys.stdout.isatty(),
        os.environ.get("TERM", ""),
        "NO_COLOR" in os.environ,
    )
    return command.render_human(response, color)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return its exit status without calling :func:`sys.exit`."""
    parser = build_parser()
    try:
        namespace = parser.parse_args(argv)
    except SystemExit as exit_request:  # argparse handles --help, --version, and usage errors.
        return int(exit_request.code or 0)

    command: Command = namespace.handler
    options = _options_from(namespace)
    try:
        response = command.fetch(options.socket_path)
    except client.CtlError as error:
        print(f"{PROG}: {error}", file=sys.stderr)
        return EXIT_FAILURE

    try:
        sys.stdout.write(_render(command, options, response))
        sys.stdout.flush()
    except OSError as error:
        print(f"{PROG}: failed to write output: {error.strerror}", file=sys.stderr)
        return EXIT_FAILURE
    return EXIT_OK

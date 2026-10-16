#!/usr/bin/python3
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
"""Launcher for the Storage Lender management CLI.

Installed as <prefix>/bin/storage-lender-ctl next to the package in
<prefix>/share/storage-lender/python, so it does not depend on the interpreter's site-packages
layout. When that private directory is absent (for example after ``pip install``), the regular
import path is used.
"""

import sys
from pathlib import Path

PRIVATE_PACKAGE_DIR = Path(__file__).resolve().parent.parent / "share" / "storage-lender" / "python"
if PRIVATE_PACKAGE_DIR.is_dir():
    sys.path.insert(0, str(PRIVATE_PACKAGE_DIR))

from storage_lender_ctl.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

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

# storage-lender-ctl is a python3 package (see pyproject.toml). CMake's part is to generate the
# protocol bindings, assemble an installable copy of the package in the build tree, run its tests
# under CTest, and install it.

# The package version is declared once in _version.py; keep it equal to the CMake project version.
file(STRINGS src/storage_lender_ctl/_version.py PYTHON_CTL_VERSION_LINE REGEX "^__version__ = ")
string(REGEX REPLACE "^__version__ = \"(.*)\"$" "\\1" PYTHON_CTL_VERSION "${PYTHON_CTL_VERSION_LINE}")
if(NOT PYTHON_CTL_VERSION STREQUAL PROJECT_VERSION)
    message(FATAL_ERROR "ctl_py/src/storage_lender_ctl/_version.py declares ${PYTHON_CTL_VERSION} "
                        "but the project version is ${PROJECT_VERSION}")
endif()

# Staged layout mirrors the installed one: <stage>/share/storage-lender/python holds the package.
set(PYTHON_CTL_STAGE_DIR ${CMAKE_CURRENT_BINARY_DIR}/stage)
set(PYTHON_CTL_SITE_DIR ${PYTHON_CTL_STAGE_DIR}/share/storage-lender/python)
set(PYTHON_CTL_PACKAGE_DIR ${PYTHON_CTL_SITE_DIR}/storage_lender_ctl)

file(MAKE_DIRECTORY ${PYTHON_CTL_PACKAGE_DIR}/proto)
protobuf_generate(
    LANGUAGE python
    PROTOS ${CMAKE_SOURCE_DIR}/proto/wire.proto ${CMAKE_SOURCE_DIR}/proto/ctl.proto
    IMPORT_DIRS ${CMAKE_SOURCE_DIR}/proto
    PROTOC_OUT_DIR ${PYTHON_CTL_PACKAGE_DIR}/proto
    OUT_VAR PYTHON_CTL_GENERATED)

set(PYTHON_CTL_SOURCES
    src/storage_lender_ctl/__init__.py
    src/storage_lender_ctl/__main__.py
    src/storage_lender_ctl/_version.py
    src/storage_lender_ctl/cli.py
    src/storage_lender_ctl/client.py
    src/storage_lender_ctl/render.py
    src/storage_lender_ctl/proto/__init__.py)

set(PYTHON_CTL_STAGED ${PYTHON_CTL_GENERATED})
foreach(SOURCE IN LISTS PYTHON_CTL_SOURCES)
    string(REPLACE "src/" "" RELATIVE_PATH ${SOURCE})
    set(STAGED ${PYTHON_CTL_SITE_DIR}/${RELATIVE_PATH})
    add_custom_command(
        OUTPUT ${STAGED}
        COMMAND ${CMAKE_COMMAND} -E copy_if_different ${CMAKE_CURRENT_SOURCE_DIR}/${SOURCE} ${STAGED}
        DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/${SOURCE}
        COMMENT "Staging ${SOURCE}"
        VERBATIM)
    list(APPEND PYTHON_CTL_STAGED ${STAGED})
endforeach()

# The launcher is a plain script: it finds the package relative to its own location.
set(PYTHON_CTL_LAUNCHER ${PYTHON_CTL_STAGE_DIR}/bin/storage-lender-ctl)
add_custom_command(
    OUTPUT ${PYTHON_CTL_LAUNCHER}
    COMMAND ${CMAKE_COMMAND} -E copy_if_different ${CMAKE_CURRENT_SOURCE_DIR}/bin/storage-lender-ctl.py
            ${PYTHON_CTL_LAUNCHER}
    COMMAND chmod 755 ${PYTHON_CTL_LAUNCHER}
    DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/bin/storage-lender-ctl.py
    COMMENT "Staging storage-lender-ctl"
    VERBATIM)
list(APPEND PYTHON_CTL_STAGED ${PYTHON_CTL_LAUNCHER})

add_custom_target(StorageLenderCtlPy ALL DEPENDS ${PYTHON_CTL_STAGED})

# Installed layout matches the staged one. This replaces the C++ storage-lender-ctl binary, which
# ctl/CMakeLists.txt skips when BUILD_PYTHON_CTL is ON.
install(
    DIRECTORY ${PYTHON_CTL_PACKAGE_DIR}
    DESTINATION ${CMAKE_INSTALL_DATADIR}/storage-lender/python
    PATTERN "__pycache__" EXCLUDE)
install(
    PROGRAMS bin/storage-lender-ctl.py
    DESTINATION ${CMAKE_INSTALL_BINDIR}
    RENAME storage-lender-ctl)

if(BUILD_TESTS)
    add_lender_python_test(
        NAME
        StorageLenderCtlPyTests
        PATH
        ${CMAKE_CURRENT_SOURCE_DIR}/tests
        PYTHONPATH
        ${PYTHON_CTL_SITE_DIR}
        LABELS
        ctl
        unit)
    set_tests_properties(StorageLenderCtlPyTests PROPERTIES ENVIRONMENT_MODIFICATION
                                                          "STORAGE_LENDER_CTL_LAUNCHER=set:${PYTHON_CTL_LAUNCHER}")

    # Run the existing end-to-end ctl test against the staged launcher and a real server.
    add_lender_test(
        NAME
        StorageLenderCtlPyIntegrationTest
        SOURCES
        ${CMAKE_SOURCE_DIR}/ctl/tests/integration_test.cpp
        LIBRARIES
        StorageLender::Server::TestSupport
        LABELS
        ctl
        integration)
    add_dependencies(StorageLenderCtlPyIntegrationTest StorageLenderCtlPy)
    target_compile_definitions(StorageLenderCtlPyIntegrationTest
                               PRIVATE STORAGE_LENDER_CTL_PATH="${PYTHON_CTL_LAUNCHER}")
endif()

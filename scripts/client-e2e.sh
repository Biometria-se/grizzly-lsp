#!/usr/bin/env bash

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

vscode_client_dir="${SCRIPT_DIR}/../client/vscode"

export CODE_TESTS_PATH="${vscode_client_dir}/out/tests"
export CODE_TESTS_WORKSPACE="${SCRIPT_DIR}/../tests/project"

xvfb-maybe node "${vscode_client_dir}/out/tests/runTest" 2>&1 | grep -vE 'Failed to connect to the bus:|ERROR:viz_main_impl.cc|ERROR:sandbox_linux.cc|ERROR:gpu_memory_buffer_support_x11.cc|ERROR:command_buffer_proxy_impl.cc'
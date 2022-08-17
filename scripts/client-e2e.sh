#!/usr/bin/env bash

set -o pipefail

main() {
    local SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
    local what="${1:-vscode}"
    local rc=1

    case "${what}" in
        "vscode")
            vscode_client_dir="${SCRIPT_DIR}/../client/vscode"

            export CODE_TESTS_PATH="${vscode_client_dir}/out/tests"
            export CODE_TESTS_WORKSPACE="${SCRIPT_DIR}/../tests/project"

            node "${vscode_client_dir}/out/tests/runTest" 2>&1 | grep -vE 'Failed to connect to the bus:|ERROR:viz_main_impl.cc|ERROR:sandbox_linux.cc|ERROR:gpu_memory_buffer_support_x11.cc|ERROR:command_buffer_proxy_impl.cc'
            rc=$?
            ;;
        *)
            >&2 echo "unknown parameter: ${what}"
            rc=1
            ;;
    esac

    return $rc
}

main "$@"
exit $?

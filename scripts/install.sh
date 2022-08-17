#!/usr/bin/env bash

set -e

main() {
    local what="${1}"
    local script_dir
    script_dir=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

    if [[ -z "${what}" || "${what}" == "server" ]]; then
        pushd "${script_dir}/../grizzly-ls" &> /dev/null
        touch setup.cfg
        python3 -m pip install -e .[dev] || { rm setup.cfg; exit 1; }
        rm setup.cfg
        popd &> /dev/null
    fi

    if [[ -z "${what}" || "${what}" == "client/"* ]]; then
        pushd "${script_dir}/../${what}" &> /dev/null
        npm install
        popd &> /dev/null
    fi

    return 0
}

main "$@"
exit $?

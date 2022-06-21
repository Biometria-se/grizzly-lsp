#!/usr/bin/env bash

export CODE_TESTS_PATH="$(pwd)/client/vscode/out/test"
export CODE_TESTS_WORKSPACE="$(pwd)/client/vscode/testFixture"

node "$(pwd)/client/vscode/out/test/runTest"
# grizzly-lsp

> **NOTE**: This project is currently in development, nothing has been published to the vscode extension marketplace or on pypi

This repository contains the `biometria.grizzly-vscode` (vscode extension marketplace) extension and the `grizzly-ls` (pypi) source code.

An extension makes it easier to develop load test scenarios with [`grizzly`](https://biometria-se.github.io) when you have auto-complete on step implementation expressions.

![Screenshot of keyword auto-complete](https://github.com/Biometria-se/grizzly-lsp/raw/main/assets/images/screenshot-auto-complete-keywords.png)

![Screenshot of step expressions auto-complete](https://github.com/Biometria-se/grizzly-lsp/raw/main/assets/images/screenshot-auto-complete-step-expressions.png)

## Development

### Environments

#### Devcontainer

Install Visual Studio Code and the "Remote - Containers" extension and open the project in the provided devcontainer.

#### Locally

-   Create a python virtual environment: `python3 -m venv <path>/grizzly-ls`
-   Activate the virtual environment: `source <path>/grizzly-ls/bin/activate`
-   Run `scripts/install.sh`
-   Start `code`

## Debug extension

-   Start server with `grizzly-ls --socket --verbose`
-   Press Ctrl+Shift+B to start compiling the client and server in [watch mode](https://code.visualstudio.com/docs/editor/tasks#:~:text=The%20first%20entry%20executes,the%20HelloWorld.js%20file.).
-   Switch to the Run and Debug View in the Sidebar (Ctrl+Shift+D).
-   Select `Launch Client` from the drop down (if it is not already).
-   Press ▷ to run the launch config (F5).
-   In the [Extension Development Host](https://code.visualstudio.com/api/get-started/your-first-extension#:~:text=Then%2C%20inside%20the%20editor%2C%20press%20F5.%20This%20will%20compile%20and%20run%20the%20extension%20in%20a%20new%20Extension%20Development%20Host%20window.) instance of VSCode
    -   Open directory `tests/project`
    -   Open file `features/project.feature`
    -   Watch console output where you started `grizzly-ls`

# grizzly-lsp

This repository contains the `biometria.grizzly-loadtester-vscode` (vscode extension marketplace) extension and the `grizzly-ls` (pypi) source code.

An extension makes it easier to develop load test scenarios with [`grizzly`](https://biometria-se.github.io) (it _can_ work with any [`behave`](https://behave.readthedocs.io/en/latest/) based project) when you have auto-complete on step implementation expressions.

To be able to use this extension, you would also have to install `grizzly-loadtester-ls`:

```bash
python -m pip install grizzly-loadtester-ls
```

![Screenshot of keyword auto-complete](https://github.com/Biometria-se/grizzly-lsp/raw/main/assets/images/screenshot-auto-complete-keywords.png)

![Screenshot of step expressions auto-complete](https://github.com/Biometria-se/grizzly-lsp/raw/main/assets/images/screenshot-auto-complete-step-expressions.png)

![Screenshot of hover help text](https://github.com/Biometria-se/grizzly-lsp/raw/main/assets/images/screenshot-hover-help.png)

![Animation of diagnostics](https://github.com/Biometria-se/grizzly-lsp/raw/main/assets/images/grizzly-ls-diagnostics.gif)

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

-   Switch to the Run and Debug View in the Sidebar (Ctrl+Shift+D).
-   Select `Launch Client` from the drop down (if it is not selected already).
-   Press ▷ to run the launch config (F5).
-   In the [Extension Development Host](https://code.visualstudio.com/api/get-started/your-first-extension#:~:text=Then%2C%20inside%20the%20editor%2C%20press%20F5.%20This%20will%20compile%20and%20run%20the%20extension%20in%20a%20new%20Extension%20Development%20Host%20window.) instance of VSCode
    -   Open file `features/project.feature`

# See here for image contents: https://github.com/microsoft/vscode-dev-containers/tree/v0.183.0/containers/python-3/.devcontainer/base.Dockerfile

# [Choice] Python version: 3, 3.9, 3.8, 3.7, 3.6
ARG VARIANT="3.12"
FROM mcr.microsoft.com/vscode/devcontainers/python:1-${VARIANT}

RUN rm  -rf /etc/apt/sources.list.d/yarn.list || true && \
    apt-get update

# [Option] Install Node.js
ARG INSTALL_NODE="true"
ARG NODE_VERSION="lts/*"
RUN if [ "${INSTALL_NODE}" = "true" ]; then su vscode -c "umask 0002 && . /usr/local/share/nvm/nvm.sh && nvm install ${NODE_VERSION} 2>&1"; fi

# [Optional] If your pip requirements rarely change, uncomment this section to add them to the image.
# COPY requirements.txt /tmp/pip-tmp/
# RUN pip3 --disable-pip-version-check --no-cache-dir install -r /tmp/pip-tmp/requirements.txt \
#    && rm -rf /tmp/pip-tmp

RUN python3 -m pip install --upgrade pip

ENV PATH=$PATH:/home/vscode/.local/bin

# [Optional] Uncomment this section to install additional OS packages.
RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install xvfb libatk1.0-0 libatk-bridge2.0-0 libgtk-3-0 libgbm1 libasound2

# run github workflows locally
RUN curl https://raw.githubusercontent.com/nektos/act/master/install.sh | sudo bash

# [Optional] Uncomment this line to install global node packages.
RUN su vscode -c "source /usr/local/share/nvm/nvm.sh && npm install -g xvfb-maybe @vscode/vsce" 2>&1

RUN rm -rf /etc/localtime || true

ARG USERNAME=vscode

RUN SNIPPET="export PROMPT_COMMAND='history -a' && export HISTFILE=/commandhistory/.bash_history" \
    && mkdir /commandhistory \
    && touch /commandhistory/.bash_history \
    && chown -R $USERNAME /commandhistory \
    && echo "$SNIPPET" >> "/home/$USERNAME/.bashrc"

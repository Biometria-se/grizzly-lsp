'use strict';

import * as net from 'net';

import { workspace, ExtensionContext } from 'vscode';
import {
    LanguageClient,
    LanguageClientOptions,
    ServerOptions,
} from 'vscode-languageclient/node';

function createStdioLanguageServer(command: string, args: string[], documentSelector: string[]): LanguageClient {
    const serverOptions: ServerOptions = {
        command,
        args,
    };

    const clientOptions: LanguageClientOptions = {
        documentSelector: documentSelector,
        synchronize: {
            configurationSection: "grizzly",  // @TODO: should be implemented using a pull workspace/section thingy
        }
    }

    return new LanguageClient(command, serverOptions, clientOptions);
}

function createSocketLanguageServer(host: string, port: number, documentSelector: string[]): LanguageClient {
    const serverOptions: ServerOptions = () => {
        return new Promise((resolve, reject) => {
            let client = new net.Socket();
            client.connect(port, host, () => {
                resolve({
                    reader: client,
                    writer: client,
                })
            });
        });
    };

    const clientOptions: LanguageClientOptions = {
        documentSelector: documentSelector,
    };

    return new LanguageClient(`socket language server (${host}:${port})`, serverOptions, clientOptions);
}

export function activate(context: ExtensionContext) {
    const configuration = workspace.getConfiguration("grizzly");
    const documentSelector = ["grizzly-gherkin"];

    let languageClient: LanguageClient

    const connection_type = configuration.get<string>("server.connection");
    switch (connection_type) {
        case "stdio":
            languageClient = createStdioLanguageServer(
                configuration.get<string>("stdio.executable"),
                configuration.get<Array<string>>("stdio.args"),
                documentSelector,
            );
            break;
        case "socket":
            languageClient = createSocketLanguageServer(
                configuration.get<string>("socket.host"),
                configuration.get<number>("socket.port"),
                documentSelector,
            );
            break;
        default:
            throw new Error(`${connection_type} is not a valid setting for grizzly.server.connection`);
    }

    context.subscriptions.push(languageClient.start());
}
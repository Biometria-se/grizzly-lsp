'use strict';

import * as net from 'net';

import {
    workspace,
    OutputChannel,
    window as Window,
    TextDocument,
    WorkspaceFoldersChangeEvent,
    WorkspaceFolder,
    Uri,
} from 'vscode';
import { LanguageClient, LanguageClientOptions, ServerOptions } from 'vscode-languageclient/node';

const clients: Map<string, LanguageClient> = new Map();

let _sortedWorkspaceFolders: string[] | undefined;

function sortedWorkspaceFolders(): string[] {
    if (_sortedWorkspaceFolders === void 0) {
        _sortedWorkspaceFolders = workspace.workspaceFolders
            ? workspace.workspaceFolders
                .map((folder) => {
                    let result = folder.uri.toString();
                    if (result.charAt(result.length - 1) !== '/') {
                        result = result + '/';
                    }

                    return result;
                })
                .sort((a, b) => {
                    return a.length - b.length;
                })
            : [];
    }

    return _sortedWorkspaceFolders;
}

workspace.onDidChangeWorkspaceFolders(() => (_sortedWorkspaceFolders = undefined));

function getOuterMostWorkspaceFolder(folder: WorkspaceFolder): WorkspaceFolder {
    const foldersSorted = sortedWorkspaceFolders();
    let folderUri = folder.uri.toString();

    for (const folderSorted of foldersSorted) {
        if (folderUri.charAt(folderUri.length - 1) !== '/') {
            folderUri = folderUri + '/';
        }

        if (folderUri.startsWith(folderSorted)) {
            return workspace.getWorkspaceFolder(Uri.parse(folderSorted)) || folder;
        }
    }

    return folder;
}

function createStdioLanguageServer(
    command: string,
    args: string[],
    documentSelector: string[],
    outputChannel: OutputChannel
): LanguageClient {
    if (process.env.VERBOSE && !args.includes('--verbose')) {
        args = [...args, '--verbose'];
    }

    const serverOptions: ServerOptions = {
        command,
        args,
    };

    const clientOptions: LanguageClientOptions = {
        documentSelector: documentSelector,
        synchronize: {
            configurationSection: 'grizzly', // @TODO: should be implemented using a pull workspace/section thingy
        },
        outputChannel,
    };

    return new LanguageClient(command, serverOptions, clientOptions);
}

function createSocketLanguageServer(
    host: string,
    port: number,
    documentSelector: string[],
    outputChannel: OutputChannel
): LanguageClient {
    const serverOptions: ServerOptions = () => {
        return new Promise((resolve) => {
            const client = new net.Socket();
            client.connect(port, host, () => {
                resolve({
                    reader: client,
                    writer: client,
                });
            });
        });
    };

    const clientOptions: LanguageClientOptions = {
        documentSelector: documentSelector,
        outputChannel: outputChannel,
    };

    return new LanguageClient(`socket language server (${host}:${port})`, serverOptions, clientOptions);
}

function createLanguageClient(): LanguageClient {
    const configuration = workspace.getConfiguration('grizzly');
    const documentSelector = ['grizzly-gherkin'];
    const outputChannel: OutputChannel = Window.createOutputChannel('grizzly language server');
    let languageClient: LanguageClient;

    const connectionType = configuration.get<string>('server.connection');

    switch (connectionType) {
        case 'stdio':
            languageClient = createStdioLanguageServer(
                configuration.get<string>('stdio.executable') || 'grizzly-ls',
                configuration.get<Array<string>>('stdio.args') || [],
                documentSelector,
                outputChannel
            );
            break;
        case 'socket':
            languageClient = createSocketLanguageServer(
                configuration.get<string>('socket.host') || 'localhost',
                configuration.get<number>('socket.port') || 4444,
                documentSelector,
                outputChannel
            );
            break;
        default:
            throw new Error(`${connectionType} is not a valid setting for grizzly.server.connection`);
    }

    return languageClient;
}

export function activate() {
    const didOpenTextDocument = async (document: TextDocument): Promise<void> => {
        if (document.languageId !== 'grizzly-gherkin') {
            return;
        }

        let folder = workspace.getWorkspaceFolder(document.uri);

        if (!folder) {
            return;
        }

        folder = getOuterMostWorkspaceFolder(folder);
        const folderUri = folder.uri.toString();

        if (!clients.has(folderUri)) {
            const client = createLanguageClient();
            client.start();
            await client.onReady();
            clients.set(folderUri, client);
        }
    };

    workspace.onDidOpenTextDocument(didOpenTextDocument);
    workspace.textDocuments.forEach(didOpenTextDocument);
    workspace.onDidChangeWorkspaceFolders((event: WorkspaceFoldersChangeEvent) => {
        for (const folder of event.removed) {
            const folderUri = folder.uri.toString();
            const client = clients.get(folderUri);

            if (client) {
                clients.delete(folderUri);
                client.stop();
            }
        }
    });
}

export async function deactivate() {
    const promises: Thenable<void>[] = [];

    for (const client of clients.values()) {
        promises.push(client.stop());
    }

    await Promise.all(promises);
}

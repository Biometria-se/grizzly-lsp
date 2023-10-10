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
    ConfigurationChangeEvent,
} from 'vscode';
import { LanguageClient, LanguageClientOptions, ServerOptions } from 'vscode-languageclient/node';

const clients: Map<string, LanguageClient> = new Map();

interface ExtensionStatus {
    isActivated: () => boolean;
    setActivated: () => void;
}

interface SettingsStdio {
    executable: string;
    args: string[];
}

interface SettingsSocket {
    host: string;
    port: number;
}

type SettingsServerConnection = 'socket' | 'stdio';

interface SettingsServer {
    connection: SettingsServerConnection;
}

interface Settings {
    server: SettingsServer;
    stdio: SettingsStdio;
    socket: SettingsSocket;
    variable_pattern: string[];
    pip_extra_index_url: string;
    use_virtual_environment: boolean;
    diagnostics_on_save_only: boolean;
}

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
    outputChannel: OutputChannel,
    initializationOptions: Settings,
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
        markdown: {
            isTrusted: true,
        },
        outputChannel,
        initializationOptions,
    };

    return new LanguageClient(command, serverOptions, clientOptions);
}

function createSocketLanguageServer(
    host: string,
    port: number,
    documentSelector: string[],
    outputChannel: OutputChannel,
    initializationOptions: Settings,
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
        markdown: {
            isTrusted: true,
        },
        initializationOptions,
    };

    return new LanguageClient(`socket language server (${host}:${port})`, serverOptions, clientOptions);
}

function createLanguageClient(outputChannel: OutputChannel): LanguageClient {
    const configuration = workspace.getConfiguration('grizzly');
    const documentSelector = ['grizzly-gherkin'];
    let languageClient: LanguageClient;

    const connectionType = configuration.get<string>('server.connection');

    const settings = <Settings>(<unknown>configuration);

    switch (connectionType) {
        case 'stdio':
            languageClient = createStdioLanguageServer(
                configuration.get<string>('stdio.executable') || 'grizzly-ls',
                configuration.get<Array<string>>('stdio.args') || [],
                documentSelector,
                outputChannel,
                settings,
            );
            break;
        case 'socket':
            languageClient = createSocketLanguageServer(
                configuration.get<string>('socket.host') || 'localhost',
                configuration.get<number>('socket.port') || 4444,
                documentSelector,
                outputChannel,
                settings,
            );
            break;
        default:
            throw new Error(`${connectionType} is not a valid setting for grizzly.server.connection`);
    }

    return languageClient;
}

export function activate(): ExtensionStatus {
    const outputChannel: OutputChannel = Window.createOutputChannel('Grizzly Language Server');

    let activated = false;

    const status: ExtensionStatus = {
        isActivated: () => {
            return activated;
        },
        setActivated: () => {
            activated = true;
        }
    };

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
            const client = createLanguageClient(outputChannel);
            await client.start();
            clients.set(folderUri, client);
            outputChannel.appendLine(`started language client for ${folderUri}`);
            await client.sendRequest('grizzly-ls/install', document.uri);
            outputChannel.appendLine('ensured dependencies');
            status.setActivated();
        }
    };

    // disable vscode builtin handler of `file://` url's, since it interferse with grizzly-ls definitions
    // https://github.com/microsoft/vscode/blob/f1f645f4ccbee9d56d091b819a81d34af31be17f/src/vs/editor/contrib/links/links.ts#L310-L330
    const configuration = workspace.getConfiguration('', {languageId: 'grizzly-gherkin'});
    configuration.update('editor.links', false, false, true);

    workspace.onDidOpenTextDocument(didOpenTextDocument);
    workspace.textDocuments.forEach(didOpenTextDocument);
    workspace.onDidChangeWorkspaceFolders(async (event: WorkspaceFoldersChangeEvent) => {
        event.removed.forEach(async (folder) => {
            const folderUri = folder.uri.toString();
            const client = clients.get(folderUri);

            if (client) {
                clients.delete(folderUri);
                outputChannel.appendLine(`removed workspace folder ${folderUri}`);
                await client.stop();
            }
        });
    });
    workspace.onDidChangeConfiguration((event: ConfigurationChangeEvent) => {
        if (!event.affectsConfiguration('grizzly')) {
            return;
        }
        outputChannel.appendLine('configuration change for "grizzly"');
    });

    return status;
}

export async function deactivate() {
    const promises: Thenable<void>[] = [];

    clients.forEach((client) => {
        promises.push(client.stop());
    });

    await Promise.all(promises);
}

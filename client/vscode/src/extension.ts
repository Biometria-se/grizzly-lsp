'use strict';

import * as net from 'net';
import * as vscode from 'vscode';
import * as util from 'util';
import * as child_process from 'child_process';
import * as path from 'path';

import { LanguageClient, LanguageClientOptions, ServerOptions, State } from 'vscode-languageclient/node';
import { PythonExtension } from '@vscode/python-extension';

import { Settings, ExtensionStatus } from './model';

const exec = util.promisify(child_process.exec);

let logger: vscode.LogOutputChannel;
let client: LanguageClient;
let python: PythonExtension;
let documentUri: vscode.Uri;
let serverUri: vscode.Uri;

let starting = false;
let activated = false;

const status: ExtensionStatus = {
    isActivated: () => {
        return activated;
    },
    setActivated: (status: boolean = true) => {
        activated = status;
    }
};


async function createStdioLanguageServer(
    module: string,
    args: string[],
    documentSelector: string[],
    initializationOptions: Settings,
): Promise<LanguageClient> {
    const python = await getPythonPath();
    const command = `${python} -c "import ${module}; import inspect; print(inspect.getsourcefile(${module}));"`;

    try {
        const { stdout } = await exec(command);
        serverUri = vscode.Uri.file(path.dirname(stdout.trim()));
        logger.debug(`serverUri = "${serverUri}"`);
    } catch (error) {
        console.error(`command = "${command}", error = "${error}"`);
        logger.error(command);
        logger.error(`Failed ^ to get module path for ${module}: ${error}`);
        logger.error('Hot-reload of language server will not work');
    }

    args = ['-m', module, ...args];

    if (process.env.VERBOSE && !args.includes('--verbose')) {
        args = [...args, '--verbose'];
        logger.warn('Starting language server in verbose mode');
    }

    const serverOptions: ServerOptions = {
        command: python,
        args,
    };

    const clientOptions: LanguageClientOptions = {
        documentSelector: documentSelector,
        markdown: {
            isTrusted: true,
        },
        outputChannel: logger,
        initializationOptions,
    };

    return new LanguageClient(python, serverOptions, clientOptions);
}

function createSocketLanguageServer(
    host: string,
    port: number,
    documentSelector: string[],
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
        outputChannel: logger,
        markdown: {
            isTrusted: true,
        },
        initializationOptions,
    };

    return new LanguageClient(`socket language server (${host}:${port})`, serverOptions, clientOptions);
}

async function createLanguageClient(): Promise<LanguageClient> {
    const configuration = vscode.workspace.getConfiguration('grizzly');
    const documentSelector = ['grizzly-gherkin'];
    let languageClient: LanguageClient;

    const connectionType = configuration.get<string>('server.connection');

    const settings = <Settings>(<unknown>configuration);

    switch (connectionType) {
        case 'stdio':
            languageClient = await createStdioLanguageServer(
                configuration.get<string>('stdio.module') || 'grizzly_ls',
                configuration.get<Array<string>>('stdio.args') || [],
                documentSelector,
                settings,
            );
            break;
        case 'socket':
            languageClient = createSocketLanguageServer(
                configuration.get<string>('socket.host') || 'localhost',
                configuration.get<number>('socket.port') || 4444,
                documentSelector,
                settings,
            );
            break;
        default:
            throw new Error(`${connectionType} is not a valid setting for grizzly.server.connection`);
    }

    return languageClient;
}

async function getPythonPath(): Promise<string> {
    // make sure all environments are loaded
    await python.environments.refreshEnvironments();

    for (const e of python.environments.known) {
        console.log(`found ${e.executable.uri.fsPath}`);
    }

    console.log(`VIRTUAL_ENV=${process.env['VIRTUAL_ENV']}`);

    // use virtual env, if one is active
    const envPath = process.env['VIRTUAL_ENV'] || python.environments.getActiveEnvironmentPath().path;

    logger.debug(`Active environment path: ${envPath}`);
    console.log(`Active environment path: ${envPath}`);

    const env = await python.environments.resolveEnvironment(envPath);

    if (!env) {
        throw new Error(`Unable to resolve environment: ${env}`);
    }

    const pythonUri = env.executable.uri;
    if (!pythonUri) {
        throw new Error('Python executable URI not found');
    }

    logger.info(`Using interpreter: ${pythonUri.fsPath}`);
    console.log(`Using interpreter: ${pythonUri.fsPath}`);

    return pythonUri.fsPath;
}

async function getPythonExtension(): Promise<void> {
    try {
        python = await PythonExtension.api();
    } catch (err) {
        logger.error(`Unable to load python extension: ${err}`);
    }
}

async function startLanguageServer(): Promise<void> {
    if (starting) {
        return;
    }

    starting = true;
    if (client) {
        await stopLanguageServer();
    }

    try {
        client = await createLanguageClient();
        await client.start();
        logger.info(`Installing based on ${documentUri.path}`);
        await client.sendRequest('grizzly-ls/install', {});
        status.setActivated(true);
    } catch (error) {
        logger.error(`Unable to start language server: ${error}`);
    } finally {
        starting = false;
    }
}

async function stopLanguageServer(): Promise<void> {
    if (!client) {
        return;
    }

    if (client.state === State.Running) {
        await client.stop();
    }

    status.setActivated(false);

    client.dispose();
    client = undefined;
}

export async function activate(context: vscode.ExtensionContext): Promise<ExtensionStatus | undefined> {
    logger = vscode.window.createOutputChannel('Grizzly Language Server', {log: true});
    logger.show();

    await getPythonExtension();
    if (!python) {
        return;
    }

    context.subscriptions.push(
        vscode.commands.registerCommand('grizzly.server.restart', async () => {
            if (status.isActivated()) {
                logger.info('Restarting language server');
                await startLanguageServer();
            }
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('grizzly.server.inventory.rebuild', async () => {
            if (client) {
                vscode.workspace.textDocuments.forEach(async (textDocument: vscode.TextDocument) => {
                    await textDocument.save();
                });
                await vscode.commands.executeCommand('grizzly-ls/rebuild-inventory');
            }
        })
    );

    context.subscriptions.push(
        python.environments.onDidChangeActiveEnvironmentPath(async () => {
            if (client) {
                logger.info('Python environment modified, restarting server');
                await startLanguageServer();
            }
        })
    );

    context.subscriptions.push(
        vscode.workspace.onDidChangeConfiguration(async (event) => {
            if (event.affectsConfiguration('grizzly') && status.isActivated()) {
                logger.info('Settings changed, restarting server');
                await startLanguageServer();
            }
        })
    );

    context.subscriptions.push(
        vscode.workspace.onDidOpenTextDocument(async (textDocument: vscode.TextDocument) => {
            if (!client && textDocument.languageId === 'grizzly-gherkin') {
                documentUri = textDocument.uri;
                await startLanguageServer();
            }
        })
    );

    // hot reload
    context.subscriptions.push(
        vscode.workspace.onDidSaveTextDocument(async (textDocument: vscode.TextDocument) => {
            if (serverUri !== undefined && textDocument.uri.path.startsWith(serverUri.path)) {
                logger.info(`Hot-reloading server: ${textDocument.uri.toString()} modified`);
                await startLanguageServer();
            }
        })
    );

    // all open files
    vscode.workspace.textDocuments.forEach(async (textDocument: vscode.TextDocument) => {
        if (!client && textDocument.languageId === 'grizzly-gherkin') {
            documentUri = textDocument.uri;
            await startLanguageServer();
        }
    });

    // disable vscode builtin handler of `file://` url's, since it interferse with grizzly-ls definitions
    // https://github.com/microsoft/vscode/blob/f1f645f4ccbee9d56d091b819a81d34af31be17f/src/vs/editor/contrib/links/links.ts#L310-L330
    const configuration = vscode.workspace.getConfiguration('', {languageId: 'grizzly-gherkin'});
    configuration.update('editor.links', false, false, true);

    return status;
}

export function deactivate(): Thenable<void> {
    return stopLanguageServer();
}

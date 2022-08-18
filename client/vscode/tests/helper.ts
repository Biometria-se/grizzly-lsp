/* --------------------------------------------------------------------------------------------
 * Copyright (c) Microsoft Corporation. All rights reserved.
 * Licensed under the MIT License. See License.txt in the project root for license information.
 * ------------------------------------------------------------------------------------------ */

import * as vscode from 'vscode';
import * as path from 'path';

export let doc: vscode.TextDocument;
export let editor: vscode.TextEditor;
export let documentEol: string;
export let platformEol: string;

const testWorkspace: string = path.resolve(__dirname, '../../../../tests/project');

const docUriActivated: Map<string, boolean> = new Map();

/**
 * Activates the vscode.lsp-sample extension
 */
export async function activate(docUri: vscode.Uri) {
    // @TODO: fugly, first time a virtual environment needs to be created, which takes time
    const activated = docUriActivated.get(docUri.toString());
    let sleep_time = 5000;

    if (activated) {
        sleep_time = 500;
    } else {
        docUriActivated.set(docUri.toString(), true);
    }

    // The extensionId is `publisher.name` from package.json
    const ext = vscode.extensions.getExtension('biometria-se.grizzly-vscode');
    await ext.activate();
    try {
        doc = await vscode.workspace.openTextDocument(docUri);
        editor = await vscode.window.showTextDocument(doc);
        await sleep(sleep_time); // Wait for server activation
    } catch (e) {
        console.error(e);
    }
}

async function sleep(ms: number) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

export const getDocPath = (p: string) => {
    return path.resolve(testWorkspace, p);
};
export const getDocUri = (p: string) => {
    return vscode.Uri.file(getDocPath(p));
};

export async function setTestContent(content: string): Promise<boolean> {
    const all = new vscode.Range(doc.positionAt(0), doc.positionAt(doc.getText().length));
    return editor.edit((eb) => eb.replace(all, content));
}

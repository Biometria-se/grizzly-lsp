import * as vscode from 'vscode';
import * as path from 'path';

export let doc: vscode.TextDocument | undefined = undefined;
export let editor: vscode.TextEditor | undefined = undefined;
export let documentEol: string;
export let platformEol: string;

export const testWorkspace: string = path.resolve(__dirname, '../../../../tests/project');

/**
 * Activates the biometria-se.vscode-grizzly extension
 */
export async function activate(docUri: vscode.Uri, content: string) {
    // The extensionId is `publisher.name` from package.json
    const ext = vscode.extensions.getExtension('biometria-se.grizzly-loadtester-vscode');
    await ext.activate();
    try {
        doc = await vscode.workspace.openTextDocument(docUri);
        editor = await vscode.window.showTextDocument(doc);

        await setTestContent(content);

        // if the extension for some reason won't start, it is nice to look at the output
        // to be able to understand why
        if (ext.exports === undefined) {
            await sleep(1000*60*60*24);
        }

        // wait until language server is done with everything
        while (!ext.exports.isActivated()) {
            await sleep(1000);
        }
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

async function setTestContent(content: string): Promise<boolean> {
    const all = new vscode.Range(doc.positionAt(0), doc.positionAt(doc.getText().length));
    return editor.edit((eb) => eb.replace(all, content));
}

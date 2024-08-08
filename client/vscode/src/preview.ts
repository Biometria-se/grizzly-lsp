import * as vscode from 'vscode';
import * as path from 'path';
import { Utils } from 'vscode-uri';

export interface GherkinPreviewOptions {
    document?: vscode.TextDocument;
    content?: string;
}


export class GherkinPreview {
    public panels: Map<vscode.Uri, vscode.WebviewPanel>;

    private style: string;

    private displayColumn = {
        viewColumn: vscode.ViewColumn.Beside,
        preserveFocus: true,
    };

    constructor(private readonly context: vscode.ExtensionContext, private readonly logger: vscode.LogOutputChannel) {
        this.panels = new Map();

        const colorThemeKind = vscode.window.activeColorTheme.kind;

        switch (colorThemeKind) {
            case vscode.ColorThemeKind.HighContrastLight:
            case vscode.ColorThemeKind.Light:
                this.style = 'github';
                break;
            case vscode.ColorThemeKind.HighContrast:
            case vscode.ColorThemeKind.Dark: // dark
                this.style = 'github-dark';
                break;
        }
    }

    private create(uri: vscode.Uri) {
        const basename = path.basename(uri.path);

        const panel = vscode.window.createWebviewPanel('grizzly.gherkin.preview', `Preview: ${basename}`, this.displayColumn, {
            enableFindWidget: false,
            enableScripts: true,
            retainContextWhenHidden: true,
            localResourceRoots: [
                Utils.joinPath(this.context.extensionUri, 'images'),
            ]
        });

        panel.iconPath = Utils.joinPath(this.context.extensionUri, 'images', 'icon.png');

        return panel;
    }

    private generateHtml(content: string, success: boolean): string {
        const language = success ? 'gherkin' : 'python';
        return `<!doctype html>
<html class="no-js" lang="en">

<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">

  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/${this.style}.min.css">

  <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/${language}.min.js"></script>
  <script>hljs.highlightAll();</script>

  <style>
  body .hljs {
    background: var(--vscode-editor-background);
  }

  pre > code {
    font-size: var(--vscode-editor-font-size);
    font-family: var(--vscode-editor-font-family);
  }
  </style>

  <title>Gherkin Preview</title>
</head>

<body>
    <pre><code class="language-${language}">${content}</code></pre>
</body>

</html>`;
    }

    public async update(textDocument: vscode.TextDocument, panel?: vscode.WebviewPanel, on_the_fly: boolean = false): Promise<void> {
        if (!panel) {
            panel = this.panels.get(textDocument.uri);
            if (!panel) return;
        }

        const [success, content]: [boolean, string | undefined] = await vscode.commands.executeCommand(
            'grizzly-ls/render-gherkin', {
                content: textDocument.getText(),
                uri: textDocument.uri.path,
                on_the_fly,
            }
        );

        if (content) {
            panel.webview.html = this.generateHtml(content, success);
        }

        return;
    }

    public close(textDocument: vscode.TextDocument): boolean {
        const panel = this.panels.get(textDocument.uri);

        if (panel) {
            panel.dispose();
            return this.panels.delete(textDocument.uri);
        }

        return false;
    }

    public async preview(textDocument: vscode.TextDocument): Promise<void> {
        let panel = this.panels.get(textDocument.uri);

        if (!panel) {
            const content = textDocument.getText();
            if (!content.includes('{% scenario')) {
                const basename = path.basename(textDocument.uri.path);
                await vscode.window.showInformationMessage(`WYSIWYG: ${basename} does not need to be previewed`);
                return;
            }

            panel = this.create(textDocument.uri);

            if (!panel) {
                return;
            }

            this.panels.set(textDocument.uri, panel);

            panel.onDidChangeViewState(() => this.update(textDocument));
            panel.onDidDispose(() => {
                return this.close(textDocument), undefined, this.context.subscriptions;
            });
        } else {
            panel.reveal(this.displayColumn.viewColumn, this.displayColumn.preserveFocus);
        }

        this.update(textDocument, panel);
    }
}

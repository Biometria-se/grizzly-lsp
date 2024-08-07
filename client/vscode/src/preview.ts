import * as vscode from 'vscode';
import * as path from 'path';

export interface GherkinPreviewOptions {
    document?: vscode.TextDocument;
    content?: string;
}

export class GherkinPreview {
    constructor(private readonly context: vscode.ExtensionContext, private readonly logger: vscode.LogOutputChannel) {}

    private createPreviewPanel(uri: vscode.Uri) {
        const displayColumn = {
            viewColumn: vscode.ViewColumn.Beside,
            preserveFocus: true,
        };

        // @TODO: base name of uri.path
        const basename = path.basename(uri.path);

        return vscode.window.createWebviewPanel('grizzly.gherkin.preview', `Preview: ${basename}`, displayColumn, {
            enableFindWidget: false,
            enableScripts: true,
            retainContextWhenHidden: true,
        });
    }

    public async createPreview(textDocument: vscode.TextDocument): Promise<vscode.WebviewPanel> {
        const panel = this.createPreviewPanel(textDocument.uri);

        if (!panel) {
            return;
        }

        // @TODO: add some listeners

        const rendered = await vscode.commands.executeCommand('grizzly-ls/render-gherkin', {content: textDocument.getText(), uri: textDocument.uri.path});

        this.logger.info(`rendered=${rendered}`);

        const content = (rendered) ? rendered : 'Failed to render, check output log';

        const colorTheme = vscode.window.activeColorTheme;
        const configuration = vscode.workspace.getConfiguration('editor');
        const fontSize = +configuration.get('fontSize');
        const fontFamily = configuration.get('fontFamily');

        let style: string;
        let backgroundColor: string;

        switch (colorTheme.kind) {
            case vscode.ColorThemeKind.HighContrastLight:
            case vscode.ColorThemeKind.Light:
                style = 'github';
                backgroundColor = '#fff';
                break;
            case vscode.ColorThemeKind.HighContrast:
            case vscode.ColorThemeKind.Dark: // dark
                style = 'github-dark';
                backgroundColor = '#0d1117';
                break;
        }

        this.logger.info(`colorTheme=${colorTheme.kind}, fontSize=${fontSize}, fontFamily=${fontFamily}`);

        panel.webview.html = `<!doctype html>
<html class="no-js" lang="en">

<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">

  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/${style}.min.css">

  <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/gherkin.min.js"></script>
  <script>hljs.highlightAll();</script>

  <style>
  body {
    background-color: ${backgroundColor};
  }
  pre > code {
    font-size: ${fontSize}px;
    font-family: ${fontFamily};
    width: 100%;
  }
  </style>

  <title>Gherkin Preview</title>
</head>

<body>
    <pre><code class="language-gherkin">${content}</code></pre>
</body>

</html>`;

        return panel;
    }
}

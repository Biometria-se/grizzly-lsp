import * as vscode from 'vscode';
import { expect } from 'chai';
import { getDocUri, activate, setTestContent } from './helper';
import { describe, it } from 'mocha';

const docUri = getDocUri('features/empty.feature');

describe('Should show help on hover step expression', () => {
    it('Hover in empty file', async () => {
        const actual = await testHover(docUri, new vscode.Position(0, 0));
        expect(actual).to.be.undefined;
    });

    it('Hover `Given a user...`', async () => {
        setTestContent(
            'Feature:\n\tScenario: test scenario\n\t\tGiven a user of type "RestApi" with weight "1" load testing "$conf::template.host"\n\t\tAnd restart scenario on failure\n'
        );

        const actual = await testHover(docUri, new vscode.Position(2, 35));

        let end = 83;
        if (process.platform == 'win32') {
            end = 84;  // due to \r\n on win32?
        }

        expect(actual.range?.start.line).to.be.equal(2);
        expect(actual.range?.start.character).to.be.equal(2);
        expect(actual.range?.end.line).to.be.equal(2);
        expect(actual.range?.end.character).to.be.equal(end);
        const contents = actual.contents[0] as vscode.MarkdownString;
        expect(contents.value).to.be
            .equal(`## Sets which type of users the scenario should use and which \`host\` is the target.
- - -
### Example:

\`\`\` gherkin
Given a user of type "RestApi" load testing "http://api.example.com"
Given a user of type "MessageQueue" load testing "mq://mqm:secret@mq.example.com/?QueueManager=QMGR01&Channel=Channel01"
Given a user of type "ServiceBus" load testing "sb://sb.example.com/;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=abc123def456ghi789="
Given a user of type "BlobStorage" load testing "DefaultEndpointsProtocol=https;EndpointSuffix=core.windows.net;AccountName=examplestorage;AccountKey=xxxyyyyzzz=="
\`\`\`
- - -
### Arguments:
* user_class_name \`str\`: name of an implementation of users, with or without \`User\`-suffix
* host \`str\`: an URL for the target host, format depends on which users is specified`);
    });
});

async function testHover(docUri: vscode.Uri, position: vscode.Position): Promise<vscode.Hover> {
    await activate(docUri);

    const [hover] = (await vscode.commands.executeCommand(
        'vscode.executeHoverProvider',
        docUri,
        position
    )) as vscode.Hover[];

    return hover;
}
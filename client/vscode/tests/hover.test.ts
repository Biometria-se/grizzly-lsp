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
            .equal(`Sets which type of users the scenario should use and which \`host\` is the target,
together with \`weight\` of the user (how many instances of this user should spawn relative to others).

Example:

\`\`\` gherkin
Given a user of type "RestApi" with weight "2" load testing "..."
Given a user of type "MessageQueue" with weight "1" load testing "..."
Given a user of type "ServiceBus" with weight "1" load testing "..."
Given a user of type "BlobStorage" with weight "4" load testing "..."
\`\`\`

Args:

* user_class_name \`str\`: name of an implementation of users, with or without \`User\`-suffix
* weight_value \`str\`: weight value for the user, default is \`1\` (see [writing a locustfile](http://docs.locust.io/en/stable/writing-a-locustfile.html#weight-attribute))
* host \`str\`: an URL for the target host, format depends on which users is specified
`);
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

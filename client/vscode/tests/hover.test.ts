import * as vscode from 'vscode';
import { expect } from 'chai';
import { getDocUri, activate } from './helper';
import { describe, it } from 'mocha';

describe('Should show help on hover step expression', () => {
    it('Hover in empty file', async () => {
        const actual = await testHover('', new vscode.Position(0, 0));
        expect(actual).to.be.undefined;
    });

    it('Hover `Given a user...`', async () => {
        const content = `Feature:
    Scenario: test scenario
        Given a user of type "RestApi" with weight "1" load testing "$conf::template.host"
        And restart scenario on failure
`;

        let end = 89;
        if (process.platform == 'win32') {
            end = 90;  // due to \r\n on win32?
        }

        const actual = await testHover(content, new vscode.Position(2, 35));

        expect(actual.range?.start.line).to.be.equal(2);
        expect(actual.range?.start.character).to.be.equal(8);
        expect(actual.range?.end.line).to.be.equal(2);
        expect(actual.range?.end.character).to.be.equal(end);
        const contents = actual.contents[0] as vscode.MarkdownString;
        expect(contents.value).to.be
            .equal(`Set which type of users the scenario should use and which \`host\` is the target,
together with \`weight\` of the user (how many instances of this user should spawn relative to others).

Example:
\`\`\`gherkin
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

    it('Hover `And restart scenario on failure`', async () => {
        const content = `Feature:
    Scenario: test scenario
        Given a user of type "RestApi" with weight "1" load testing "$conf::template.host"
        And restart scenario on failure
`;

        let end = 38;
        if (process.platform == 'win32') {
            end = 39;  // due to \r\n on win32?
        }

        const actual = await testHover(content, new vscode.Position(3, 13));

        expect(actual.range?.start.line).to.be.equal(3);
        expect(actual.range?.start.character).to.be.equal(8);
        expect(actual.range?.end.line).to.be.equal(3);
        expect(actual.range?.end.character).to.be.equal(end);

        const contents = actual.contents[0] as vscode.MarkdownString;
        expect(contents.value).to.be
            .equal(`Restart scenario, from first task, if a request fails.

!!! attention
This step is deprecated and will be removed in the future, use step_setup_failed_task_default instead.

Default behavior is to continue the scenario if a request fails.

Example:
\`\`\`gherkin
And restart scenario on failure
\`\`\`

`);
    });

});

async function testHover(content: string, position: vscode.Position): Promise<vscode.Hover> {
    const docUri = getDocUri('features/empty.feature');
    await activate(docUri, content);

    const [hover] = (await vscode.commands.executeCommand(
        'vscode.executeHoverProvider',
        docUri,
        position
    )) as vscode.Hover[];

    return hover;
}

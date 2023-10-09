import * as path from 'path';
import * as fs from 'fs';
import * as vscode from 'vscode';
import { expect } from 'chai';
import { getDocUri, activate, testWorkspace } from './helper';
import { describe, it } from 'mocha';

describe('Should do definitions for step expressions', () => {
    it('Request payload reference in step does not exist in features/requests', async () => {
        const content = `Feature: test feature
  Scenario: test scenario
    Given a user of type "RestApi" with weight "1" load testing "$conf::template.host"
    Then post request "hello.txt" with name "hello" to endpoint "/hello"
`;
        const actual = await testDefintion(content, new vscode.Position(3, 26));
        expect(actual).to.deep.equal([]);
    });

    it('Request payload reference in step does exist in features/requests', async () => {
        const content = `Feature: test feature
  Scenario: test scenario
    Given a user of type "RestApi" with weight "1" load testing "$conf::template.host"
    Then post request "hello.txt" with name "hello" to endpoint "/hello"
`;
        const payload_dir = path.resolve(testWorkspace, 'features', 'requests');
        await fs.promises.mkdir(payload_dir, {recursive: true});

        try {
            const test_txt = path.resolve(payload_dir, 'hello.txt');
            fs.closeSync(fs.openSync(test_txt, 'a'));
            let expectedTargetUri: string;
            switch (process.platform) {
                case 'win32':
                    expectedTargetUri = test_txt.replace(/\\/g, '/');
                    expectedTargetUri = `/${expectedTargetUri}`;
                    break;
                default:
                    expectedTargetUri = test_txt;
                    break;
            }
            const actual = await testDefintion(content, new vscode.Position(3, 26));
            expect(actual.length).to.be.equal(1);
            const actual_definition = actual[0];
            expect(actual_definition.targetUri.path).to.equal(expectedTargetUri);
            expect(actual_definition.originSelectionRange.start.line).to.equal(3);
            expect(actual_definition.originSelectionRange.start.character).to.equal(23);
            expect(actual_definition.originSelectionRange.end.line).to.equal(3);
            expect(actual_definition.originSelectionRange.end.character).to.equal(32);
        } finally {
            // @TODO remove directory
            await fs.promises.rm(payload_dir, {recursive: true, force: true});
        }
    });
});

async function testDefintion(content: string, position: vscode.Position): Promise<vscode.LocationLink[]> {
    const docUri = getDocUri('features/empty.feature');
    await activate(docUri, content);

    return (await vscode.commands.executeCommand(
        'vscode.executeDefinitionProvider',
        docUri,
        position,
    )) as vscode.LocationLink[];
}

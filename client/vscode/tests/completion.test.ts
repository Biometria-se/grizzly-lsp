import * as vscode from 'vscode';
import { expect } from 'chai';
import { getDocUri, activate, setTestContent } from './helper';
import { describe, it } from 'mocha';

const docUri = getDocUri('features/empty.feature');

describe('Should do completion on keywords', () => {
    it('Complete keywords, empty file, only suggest first-level keyword(s)', async () => {
        // empty document, only suggest "Feature"
        const actual = await testCompletion(docUri, new vscode.Position(0, 0));

        expect(actual.items.length).to.be.equal(1);
        expect(actual.items[0].label).to.be.equal('Feature');
        expect(actual.items[0].kind).to.be.equal(vscode.CompletionItemKind.Keyword);
    });

    it('Complete keywords, suggest second-level keywords', async () => {
        // only "Feature" present in document, suggest the two second-level keywords
        setTestContent('Feature:\n\t');

        const actual = await testCompletion(docUri, new vscode.Position(1, 0));

        expect(actual.items.length).to.be.equal(2);
        expect(actual.items.map((value) => value.label)).to.deep.equal(['Background', 'Scenario']);
        expect(actual.items.map((value) => value.kind)).to.deep.equal(
            new Array(2).fill(vscode.CompletionItemKind.Keyword)
        );
    });

    it('Complete keywords, only expect `Feature`', async () => {
        // "Background" present in document, which only occurs once, suggest only "Scenario"
        setTestContent(`Feature:
    Background:
    `);

        const actual = await testCompletion(docUri, new vscode.Position(2, 0));

        expect(actual.items.length).to.be.equal(1);
        expect(actual.items.map((value) => value.label)).to.deep.equal(['Scenario']);
        expect(actual.items.map((value) => value.kind)).to.deep.equal(
            new Array(1).fill(vscode.CompletionItemKind.Keyword)
        );
    });

    it('Complete keywords, all other keywords', async () => {
        // "Background" and "Scenario" (at least once) present, suggest all the other keywords
        setTestContent(`Feature:
    Background:
    Scenario:
    `);

        const actual = await testCompletion(docUri, new vscode.Position(3, 0));

        expect(actual.items.length).to.be.equal(6);
        expect(actual.items.map((value) => value.label)).to.deep.equal([
            'And',
            'But',
            'Given',
            'Scenario',
            'Then',
            'When',
        ]);
        expect(actual.items.map((value) => value.kind)).to.deep.equal(
            new Array(6).fill(vscode.CompletionItemKind.Keyword)
        );
    });

    it('Complete keywords, keywords containing `en` (fuzzy matching)', async () => {
        // Complete keywords containing "en"
        setTestContent(`Feature:
    Background:
    Scenario:
        en`);

        const actual = await testCompletion(docUri, new vscode.Position(3, 3));

        expect(actual.items.length).to.be.equal(4);
        expect(actual.items.map((value) => value.label)).to.deep.equal(['Given', 'Scenario', 'Then', 'When']);
        expect(actual.items.map((value) => value.kind)).to.deep.equal(
            new Array(4).fill(vscode.CompletionItemKind.Keyword)
        );
    });
});

describe('Should do completion on steps', () => {
    it('Complete steps, keyword `Given` step `variable`', async () => {
        setTestContent(`Feature:
    Background:
    Scenario:
        Given variable`);

        const actual = await testCompletion(docUri, new vscode.Position(3, 15));
        const expected = [
            'set context variable "" to ""',
            'ask for value of variable ""',
            'set global context variable "" to ""',
            'set alias "" for variable ""',
            'value for variable "" is ""',
        ];

        actual.items.forEach((item) => {
            expect(item.kind).to.be.equal(vscode.CompletionItemKind.Function);
            expect(expected).to.contain(item.label);
        });
    });

    it('Complete steps, keyword `Then` step `save`', async () => {
        setTestContent('Feature:\n\tBackground:\n\tScenario:\n\t\tThen save');

        const actual = await testCompletion(docUri, new vscode.Position(3, 10));
        const expected = [
            'save response metadata "" in variable ""',
            'save response payload "" in variable ""',
            'save response payload "" that matches "" in variable ""',
            'save response metadata "" that matches "" in variable ""',
            'get "" with name "" and save response payload in ""',
            'parse date "" and save in variable ""',
            'parse "" as "undefined" and save value of "" in variable ""',
            'parse "" as "plain" and save value of "" in variable ""',
            'parse "" as "xml" and save value of "" in variable ""',
            'parse "" as "json" and save value of "" in variable ""',
        ];

        const actualLabels = actual.items.map((item) => item.label);

        expected.forEach((e) => {
            expect(actualLabels).to.contain(e);
        });

        actual.items.forEach((item) => {
            expect(item.kind).to.be.equal(vscode.CompletionItemKind.Function);
        });

        const actualInsertText = actual.items.map((item) => {
            if (item.insertText instanceof vscode.SnippetString) {
                return item.insertText.value;
            } else {
                return item.insertText;
            }
        });
        expected.forEach((e) => {
            const parts: string[] = [];
            let index = 1;
            for (const p of e.split('""')) {
                if (p === undefined || p.length < 1) {
                    continue;
                }
                parts.push(p);
                parts.push(`"$${index++}"`);
            }
            e = parts.join('');
            expect(actualInsertText).to.contain(e);
        });
    });

    it('Complete steps, keyword `Then` step `save response metadata "hello"`', async () => {
        setTestContent('Feature:\n\tBackground:\n\tScenario:\n\t\tThen  save response metadata "hello"');
        const actual = await testCompletion(docUri, new vscode.Position(3, 37));
        const expected = [
            'save response metadata "hello" in variable ""',
            'save response metadata "hello" that matches "" in variable ""',
        ];

        const actualLabels = actual.items.map((item) => item.label);

        expected.forEach((e) => {
            expect(actualLabels).to.contain(e);
        });

        actual.items.forEach((item) => {
            expect(item.kind).to.be.equal(vscode.CompletionItemKind.Function);
        });
    });

    it('Complete steps, keyword `When` step `<null>`', async () => {
        setTestContent('Feature:\n\tBackground:\n\tScenario:\n\t\tWhen');
        const actual = await testCompletion(docUri, new vscode.Position(3, 5));
        const expected = [
            'condition "" with name "" is true, execute these tasks',
            'fail ratio is greater than ""% fail scenario',
            'average response time is greater than "" milliseconds fail scenario',
            'response time percentile ""% is greater than "" milliseconds fail scenario',
            'response payload "" is not "" fail request',
            'response payload "" is "" fail request',
            'response metadata "" is not "" fail request',
            'response metadata "" is "" fail request',
        ];

        actual.items.forEach((item) => {
            expect(item.kind).to.be.equal(vscode.CompletionItemKind.Function);
            expect(expected).to.contain(item.label);
        });
    });

    it('Complete steps, keyword `When` step `response `', async () => {
        setTestContent('Feature:\n\tBackground:\n\tScenario:\n\t\tWhen response ');
        const actual = await testCompletion(docUri, new vscode.Position(3, 15));
        const expected = [
            'average response time is greater than "" milliseconds fail scenario',
            'response time percentile ""% is greater than "" milliseconds fail scenario',
            'response payload "" is not "" fail request',
            'response payload "" is "" fail request',
            'response metadata "" is not "" fail request',
            'response metadata "" is "" fail request',
        ];

        actual.items.forEach((item) => {
            expect(item.kind).to.be.equal(vscode.CompletionItemKind.Function);
            expect(expected).to.contain(item.label);
        });
    });

    it('Complete steps, keyword `When` step `response fail request`', async () => {
        setTestContent('Feature:\n\tBackground:\n\tScenario:\n\t\tWhen response fail request');
        const actual = await testCompletion(docUri, new vscode.Position(3, 27));
        const expected = [
            'response payload "" is not "" fail request',
            'response payload "" is "" fail request',
            'response metadata "" is not "" fail request',
            'response metadata "" is "" fail request',
        ];

        actual.items.forEach((item) => {
            expect(item.kind).to.be.equal(vscode.CompletionItemKind.Function);
            expect(expected).to.contain(item.label);
        });
    });

    it('Complete steps, keyword `When` step `response payload "" is fail request`', async () => {
        setTestContent('Feature:\n\tBackground:\n\tScenario:\n\t\tWhen response payload "" is fail request');
        const actual = await testCompletion(docUri, new vscode.Position(3, 41));
        const expected = ['response payload "" is not "" fail request', 'response payload "" is "" fail request'];

        const actualLabels = actual.items.map((item) => item.label);

        expected.forEach((e) => {
            expect(actualLabels).to.contain(e);
        });

        actual.items.forEach((item) => {
            expect(item.kind).to.be.equal(vscode.CompletionItemKind.Function);
        });
    });

    it('Complete steps, keyword `And` step `repeat for "" it`', async () => {
        setTestContent('Feature:\n\tBackground:\n\tScenario:\n\t\tGiven a user of type "RestApi" load testing "https://www.example.org"\n\t\tAnd repeat for "1" it');
        const actual = await testCompletion(docUri, new vscode.Position(4, 22));

        const actualLabels = actual.items.map((item) => item.label);
        const actualInsertText = actual.items.map((item) => item.insertText);
        expect(actualInsertText).to.be.eql(['iteration', 'iterations']);
        expect(actualLabels).to.be.eql(['repeat for "1" iteration', 'repeat for "1" iterations']);
    });

    it('Complete steps, keyword `And` step `repeat for "" it `', async () => {
        setTestContent('Feature:\n\tBackground:\n\tScenario:\n\t\tGiven a user of type "RestApi" load testing "https://www.example.org"\n\t\tAnd repeat for "1" ');
        const actual = await testCompletion(docUri, new vscode.Position(4, 22));

        const actualLabels = actual.items.map((item) => item.label);
        const actualInsertText = actual.items.map((item) => item.insertText);
        expect(actualInsertText).to.be.eql(['iteration', 'iterations']);
        expect(actualLabels).to.be.eql(['repeat for "1" iteration', 'repeat for "1" iterations']);
    });

    it('Complete steps, keyword `And` step `repeat for ""`', async () => {
        setTestContent('Feature:\n\tBackground:\n\tScenario:\n\t\tGiven a user of type "RestApi" load testing "https://www.example.org"\n\t\tAnd repeat for "1"');
        const actual = await testCompletion(docUri, new vscode.Position(4, 22));

        const actualLabels = actual.items.map((item) => item.label);
        const actualInsertText = actual.items.map((item) => item.insertText);
        expect(actualInsertText).to.be.eql([' iteration', ' iterations']);
        expect(actualLabels).to.be.eql(['repeat for "1" iteration', 'repeat for "1" iterations']);
    });
});

async function testCompletion(docUri: vscode.Uri, position: vscode.Position): Promise<vscode.CompletionList> {
    await activate(docUri);

    // Executing the command `vscode.executeCompletionItemProvider` to simulate triggering completion
    return (await vscode.commands.executeCommand(
        'vscode.executeCompletionItemProvider',
        docUri,
        position
    )) as vscode.CompletionList;
}

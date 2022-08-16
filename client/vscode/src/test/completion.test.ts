/* --------------------------------------------------------------------------------------------
 * Copyright (c) Microsoft Corporation. All rights reserved.
 * Licensed under the MIT License. See License.txt in the project root for license information.
 * ------------------------------------------------------------------------------------------ */

import * as vscode from "vscode";
import { expect } from "chai";
import { getDocUri, activate, setTestContent } from "./helper";

suite("Should do completion", () => {
    const docUri = getDocUri("features/empty.feature");

    test("Complete keywords, empty file, only suggest first-level keyword(s)", async () => {
        // empty document, only suggest "Feature"
        let actual = await testCompletion(docUri, new vscode.Position(0, 0));

        expect(actual.items.length).to.be.equal(1);
        expect(actual.items[0].label).to.be.equal("Feature");
        expect(actual.items[0].kind).to.be.equal(vscode.CompletionItemKind.Keyword);
    });

    test("Complete keywords, suggest second-level keywords", async () => {
        // only "Feature" present in document, suggest the two second-level keywords
        setTestContent("Feature:\n\t");

        let actual = await testCompletion(docUri, new vscode.Position(1, 0));

        expect(actual.items.length).to.be.equal(2);
        expect(actual.items.map((value) => value.label)).to.deep.equal(["Background", "Scenario"]);
        expect(actual.items.map((value) => value.kind)).to.deep.equal(new Array(2).fill(vscode.CompletionItemKind.Keyword));
    });

    test("Complete keywords, only expect `Feature`", async () => {
        // "Background" present in document, which only occurs once, suggest only "Scenario"
        setTestContent("Feature:\n\tBackground:\n\t");

        let actual = await testCompletion(docUri, new vscode.Position(2, 0));

        expect(actual.items.length).to.be.equal(1);
        expect(actual.items.map((value) => value.label)).to.deep.equal(["Scenario"]);
        expect(actual.items.map((value) => value.kind)).to.deep.equal(new Array(1).fill(vscode.CompletionItemKind.Keyword));
    });

    test("Complete keywords, all other keywords", async () => {
        // "Background" and "Scenario" (at least once) present, suggest all the other keywords
        setTestContent("Feature:\n\tBackground:\n\tScenario:\n\t");

        let actual = await testCompletion(docUri, new vscode.Position(3, 0));

        expect(actual.items.length).to.be.equal(6)
        expect(actual.items.map((value) => value.label)).to.deep.equal(["And", "But", "Given", "Scenario", "Then", "When"]);
        expect(actual.items.map((value) => value.kind)).to.deep.equal(new Array(6).fill(vscode.CompletionItemKind.Keyword));
    });

    test("Complete keywords, keywords containing `en` (fuzzy matching)", async () => {
        // Complete keywords containing "en"
        setTestContent("Feature:\n\tBackground:\n\tScenario:\n\t\ten");

        let actual = await testCompletion(docUri, new vscode.Position(3, 3));

        expect(actual.items.length).to.be.equal(4)
        expect(actual.items.map((value) => value.label)).to.deep.equal(["Given", "Scenario", "Then", "When"]);
        expect(actual.items.map((value) => value.kind)).to.deep.equal(new Array(4).fill(vscode.CompletionItemKind.Keyword));
    });
});

async function testCompletion(
    docUri: vscode.Uri,
    position: vscode.Position,
): Promise<vscode.CompletionList> {
    await activate(docUri);

    // Executing the command `vscode.executeCompletionItemProvider` to simulate triggering completion
    return (await vscode.commands.executeCommand(
        "vscode.executeCompletionItemProvider",
        docUri,
        position,
    )) as vscode.CompletionList;
}

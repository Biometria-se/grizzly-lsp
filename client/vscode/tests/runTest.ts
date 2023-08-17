import * as path from 'path';
import * as fs from 'fs';

import { runTests } from '@vscode/test-electron';

async function main() {
    const vscode_settings = path.resolve('../../tests/project/.vscode/settings.json');
    try {
        if (fs.existsSync(vscode_settings)) {
            fs.renameSync(vscode_settings, `${vscode_settings}.bak`);
        }

        // The folder containing the Extension Manifest package.json
        // Passed to `--extensionDevelopmentPath`
        const extensionDevelopmentPath = path.resolve(__dirname, '../../');

        // The path to test runner
        // Passed to --extensionTestsPath
        const extensionTestsPath = path.resolve(__dirname, './index');

        const testWorkspace: string = path.resolve(__dirname, '../../../../tests/project');

        // Download VS Code, unzip it and run the integration test
        await runTests({
            extensionDevelopmentPath,
            extensionTestsPath,
            launchArgs: [testWorkspace, '--disable-chromium-sandbox'],
        });
    } catch (err) {
        console.error(err);
        console.error('Failed to run tests');
        process.exit(1);
    } finally {
        if (fs.existsSync(`${vscode_settings}.bak`)) {
            fs.renameSync(`${vscode_settings}.bak`, vscode_settings);
        }
    }
}

main();

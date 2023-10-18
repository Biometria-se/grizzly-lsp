import * as path from 'path';
import * as Mocha from 'mocha';
import * as glob from 'glob';
import * as vscode from 'vscode';

export function run(): Promise<void> {
    // Create the mocha test
    const mocha = new Mocha({
        ui: 'tdd',
        color: true,
    });
    mocha.timeout(100000);

    const testsRoot = __dirname;

    return new Promise((resolve, reject) => {
        console.log('available extensions:');
        vscode.extensions.all.forEach((extension) => {
            if (!extension.id.startsWith('vscode.')) {
                console.log(`${extension.id} ${extension.extensionPath}`);
            }
        });

        const tests = process.env['TESTS']?.split(',');
        glob('**.test.js', { cwd: testsRoot }, (err: Error, files: string[]) => {
            if (err) {
                return reject(err);
            }

            // Add files to the test suite
            files.forEach((f: string) => {
                if ((tests === undefined || tests.includes(`${path.parse(f).name}.ts`))) {
                    mocha.addFile(path.resolve(testsRoot, f));
                }

                return;
            });

            try {
                // Run the mocha test
                mocha.run((failures) => {
                    if (failures > 0) {
                        reject(new Error(`${failures} tests failed.`));
                    } else {
                        resolve();
                    }
                });
            } catch (err) {
                console.error(err);
                reject(err);
            }
        });
    });
}

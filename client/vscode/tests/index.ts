import * as path from 'path';
import * as Mocha from 'mocha';
import * as glob from 'glob';

export function run(): Promise<void> {
    // Create the mocha test
    const mocha = new Mocha({
        ui: 'tdd',
        color: true,
    });
    mocha.timeout(300000);

    const testsRoot = __dirname;

    return new Promise((resolve, reject) => {
        const tests = process.env['TESTS']?.split(',').map((test) => path.parse(test.replace('.ts', '.js')).base);
        glob('**.test.js', { cwd: testsRoot }, (err: Error, files: string[]) => {
            if (err) {
                return reject(err);
            }

            // Add files to the test suite
            files.forEach((f: string) => {
                if (tests === undefined || tests.includes(f)) {
                    mocha.addFile(path.resolve(testsRoot, f));
                }
            });

            mocha.slow(175);

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

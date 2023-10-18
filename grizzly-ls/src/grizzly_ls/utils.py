import os
import subprocess
import logging

from typing import Dict, List, Optional, Tuple


logger = logging.getLogger(__name__)


def run_command(
    command: List[str],
    env: Optional[Dict[str, str]] = None,
    cwd: Optional[str] = None,
) -> Tuple[int, List[str]]:
    output: List[str] = []

    if env is None:
        env = os.environ.copy()

    if cwd is None:
        cwd = os.getcwd()

    process = subprocess.Popen(
        command,
        env=env,
        cwd=cwd,
        stderr=subprocess.STDOUT,
        stdout=subprocess.PIPE,
    )

    try:
        while process.poll() is None:
            stdout = process.stdout
            if stdout is None:  # pragma: no cover
                break

            buffer = stdout.readline()
            if not buffer:
                break

            output.append(buffer.decode('utf-8'))

        process.terminate()
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        try:
            process.kill()
        except Exception:  # pragma: no cover
            pass

    process.wait()

    return process.returncode, output

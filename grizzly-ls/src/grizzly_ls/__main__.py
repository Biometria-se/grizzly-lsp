import sys
import argparse
import logging

from typing import List, Optional

from .server import GrizzlyLanguageServer


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog='grizzly-ls')

    parser.add_argument(
        '--socket',
        action='store_true',
        required=False,
        default=False,
        help='run server in socket mode',
    )

    parser.add_argument(
        '--socket-port',
        type=int,
        default=4444,
        required=False,
        help='port the language server should listen on',
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        required=False,
        default=False,
        help='verbose output from server',
    )

    parser.add_argument(
        '--no-verbose',
        nargs='+',
        type=str,
        default=None,
        help='name of loggers to disable',
    )

    parser.add_argument(
        '--version',
        action='store_true',
        required=False,
        default=False,
        help='print version and exit',
    )

    args = parser.parse_args()

    if args.version:
        from grizzly_ls import __version__

        print(__version__, file=sys.stderr)

        raise SystemExit(0)

    return args


def setup_logging(args: argparse.Namespace) -> None:
    handlers: List[logging.Handler] = []
    level = logging.INFO if not args.verbose else logging.DEBUG

    if not args.socket:
        if level < logging.INFO:
            handlers = [logging.FileHandler('grizzly-ls.log')]
    else:
        handlers = [logging.StreamHandler(sys.stderr)]

    logging.basicConfig(
        level=level,
        format='[%(asctime)s] %(levelname)s: %(message)s',
        handlers=handlers,
    )

    no_verbose: Optional[List[str]] = args.no_verbose

    if no_verbose is None:
        no_verbose = []

    # always supress these loggers
    no_verbose.append('parse')
    no_verbose.append('pip')

    for logger_name in no_verbose:
        if logger_name in logging.Logger.manager.loggerDict:
            logger = logging.getLogger(logger_name)
            logger.setLevel(logging.ERROR)
        else:
            print(f'!! logger "{logger_name}" does not exist', file=sys.stderr)


def main() -> None:
    args = parse_arguments()

    setup_logging(args)

    server = GrizzlyLanguageServer()

    if not args.socket:
        server.start_io(sys.stdin.buffer, sys.stdout.buffer)  # type: ignore
    else:
        server.start_tcp('127.0.0.1', args.socket_port)  # type: ignore


if __name__ == '__main__':  # pragma: no cover
    main()

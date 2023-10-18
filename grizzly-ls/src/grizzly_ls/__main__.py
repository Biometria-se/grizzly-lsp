import sys
import argparse
import logging

from typing import List, Optional


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
            file_handler = logging.FileHandler('grizzly-ls.log')
            file_handler.setFormatter(
                logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s')
            )
            handlers.append(file_handler)

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(logging.Formatter('server/%(levelname)s: %(message)s'))
    handlers.append(stream_handler)

    logging.basicConfig(
        level=level,
        handlers=handlers,
    )

    no_verbose: Optional[List[str]] = args.no_verbose

    if no_verbose is None:
        no_verbose = []

    # always supress these loggers
    no_verbose.append('parse')
    no_verbose.append('pip')
    if not args.verbose:
        no_verbose.append('pygls')

    for logger_name in no_verbose:
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.ERROR)


def main() -> None:
    args = parse_arguments()

    setup_logging(args)

    from grizzly_ls.server import server

    if not args.socket:
        server.start_io(sys.stdin.buffer, sys.stdout.buffer)  # type: ignore
    else:
        server.start_tcp('127.0.0.1', args.socket_port)  # type: ignore


if __name__ == '__main__':  # pragma: no cover
    main()

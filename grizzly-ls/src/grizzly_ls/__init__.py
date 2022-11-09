from importlib.metadata import version, PackageNotFoundError


try:
    __version__ = version('grizzly-loadtester-ls')
except PackageNotFoundError:
    __version__ = 'unknown'

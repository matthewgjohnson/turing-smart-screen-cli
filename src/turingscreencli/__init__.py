"""Turing Smart Screen CLI package."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("turingscreencli")
except PackageNotFoundError:
    __version__ = "0.0.0"

from .cli import create_parser, main, run

__all__ = ["__version__", "create_parser", "main", "run"]

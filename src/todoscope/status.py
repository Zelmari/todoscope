"""Transient terminal status (MS-9): spinner-free wait indicator on stderr."""

from __future__ import annotations

import sys


class StatusContext:
    """Shows a small temporary message on stderr while waiting.

    Disabled automatically when stderr is not a terminal (pipes, agents,
    redirected output). Never writes to stdout and never holds secrets.
    """

    def __init__(self, message: str = "Analyzing comments", stream=None) -> None:
        self.message = message
        self.stream = stream if stream is not None else sys.stderr
        self.active = bool(getattr(self.stream, "isatty", lambda: False)())

    def __enter__(self) -> StatusContext:
        if self.active:
            self.stream.write(f"{self.message} ...")
            self.stream.flush()
        return self

    def __exit__(self, *exc) -> None:
        if self.active:
            self.stream.write("\r" + " " * (len(self.message) + 8) + "\r")
            self.stream.flush()

"""Native-style 24-row terminal paging shared by all game bindings."""

from __future__ import annotations

import sys
from typing import Callable, TextIO


SCREEN_ROWS = 24
MORE_PROMPT = "(MORE)"


def page_chunks(text: str, rows: int = SCREEN_ROWS) -> tuple[str, ...]:
    """Split already-wrapped output into terminal pages.

    A full intermediate page reserves its last row for ``(MORE)``, hence 23
    text rows on a 24-row display.  The final page may use all 24 rows because
    it needs no prompt.
    """

    if rows < 2:
        raise ValueError("paging requires at least two screen rows")
    lines = text.split("\n")
    pages: list[str] = []
    while len(lines) > rows:
        pages.append("\n".join(lines[: rows - 1]))
        lines = lines[rows - 1 :]
    pages.append("\n".join(lines))
    return tuple(pages)


def read_single_key(stream: TextIO | None = None) -> str:
    """Wait for one key without requiring Enter (Windows console or a tty)."""

    if stream is None:
        stream = sys.stdin
    if stream is sys.stdin and stream.isatty():
        if sys.platform == "win32":
            import msvcrt

            return msvcrt.getwch()
        import termios
        import tty

        fd = stream.fileno()
        saved = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            return stream.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)
    return stream.read(1)


def print_paged(
    text: str,
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
    wait_key: Callable[[], str] | None = None,
    interactive: bool | None = None,
    rows: int = SCREEN_ROWS,
) -> None:
    """Print text with the original ``(MORE)``/single-key interaction.

    Redirected input/output is emitted in one pass.  This prevents automated
    replay, tests, and commands such as ``echo quit | run.bat`` from losing the
    first command to the pager.
    """

    if input_stream is None:
        input_stream = sys.stdin
    if output_stream is None:
        output_stream = sys.stdout
    if interactive is None:
        interactive = input_stream.isatty() and output_stream.isatty()
    if not interactive:
        print(text, file=output_stream)
        return

    pages = page_chunks(text, rows=rows)
    key_reader = wait_key or (lambda: read_single_key(input_stream))
    for index, page in enumerate(pages):
        output_stream.write(page)
        if index + 1 < len(pages):
            output_stream.write("\n" + MORE_PROMPT)
            output_stream.flush()
            key_reader()
            # Erase the prompt in place; the next page starts on that row.
            output_stream.write("\r" + " " * len(MORE_PROMPT) + "\r")
        else:
            output_stream.write("\n")
    output_stream.flush()

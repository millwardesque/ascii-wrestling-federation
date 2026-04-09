"""TTY single-key reads and line input with ESC detection (POSIX + Windows fallback)."""

from __future__ import annotations

import sys
from typing import Literal

__all__ = [
    "tty_interactive",
    "read_any_key",
    "read_key_or_esc",
    "read_title_key",
    "read_move_choice_line",
    "read_digit_1_or_2",
    "wait_enter_or_esc",
]

try:
    import select
    import termios
    import tty

    _HAS_POSIX = True
except ImportError:
    _HAS_POSIX = False

try:
    import msvcrt

    _HAS_MSVCRT = True
except ImportError:
    _HAS_MSVCRT = False


def tty_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def read_any_key() -> None:
    """Wait for one keypress (any key). On a pipe or non-TTY, consume one line."""
    if not tty_interactive():
        sys.stdin.readline()
        return
    if _HAS_POSIX:
        _read_any_key_posix()
    elif _HAS_MSVCRT:
        msvcrt.getch()
    else:
        sys.stdin.readline()


def read_title_key() -> Literal["start", "quit"]:
    """
    Title screen: any key continues; Escape exits (caller should ``sys.exit(0)``).
    """
    k = read_key_or_esc()
    if k == "ESC":
        return "quit"
    return "start"


def _read_any_key_posix() -> None:
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        b = sys.stdin.read(1)
        if ord(b) == 27:
            _drain_escape_suffix()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _drain_escape_suffix() -> None:
    """If ESC was the start of an escape sequence, consume the rest."""
    if not _HAS_POSIX:
        return
    fd = sys.stdin.fileno()
    while True:
        r, _, _ = select.select([sys.stdin], [], [], 0.02)
        if not r:
            break
        sys.stdin.read(1)


def read_key_or_esc() -> str | Literal["ESC"]:
    """
    Read one logical key. Returns ``'ESC'`` for the Escape key; otherwise one char
    (may be ``'\\r'`` or ``'\\n'`` for Enter).
    """
    if not tty_interactive():
        line = sys.stdin.readline()
        if not line:
            return "\n"
        return line[0]

    if _HAS_POSIX:
        return _read_key_or_esc_posix()
    if _HAS_MSVCRT:
        ch = msvcrt.getch()
        if ch in (b"\x1b",):
            return "ESC"
        return ch.decode("latin-1", errors="replace")
    line = sys.stdin.readline()
    return line[0] if line else "\n"


def _read_key_or_esc_posix() -> str | Literal["ESC"]:
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        b = sys.stdin.read(1)
        if not b:
            return "\n"
        if ord(b) == 27:
            _drain_escape_suffix()
            return "ESC"
        return b
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def read_move_choice_line() -> str | Literal["ESC"]:
    """
    Line mode in raw terminal: digits and backspace until Enter; ESC aborts to pause.
    Returns the line (e.g. ``'3'``) or ``'ESC'``.
    """
    if not tty_interactive():
        return sys.stdin.readline().strip()

    if not _HAS_POSIX:
        line = sys.stdin.readline().strip()
        return line

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    buf: list[str] = []
    try:
        tty.setcbreak(fd)
        while True:
            b = sys.stdin.read(1)
            if not b:
                continue
            o = ord(b)
            if o == 27:
                _drain_escape_suffix()
                return "ESC"
            if o in (13, 10):
                sys.stdout.write("\n")
                sys.stdout.flush()
                return "".join(buf)
            if o in (8, 127):
                if buf:
                    buf.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue
            if b.isdigit():
                buf.append(b)
                sys.stdout.write(b)
                sys.stdout.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def read_digit_1_or_2() -> Literal["1", "2"]:
    """Block until the user presses 1 or 2."""
    if not tty_interactive():
        while True:
            line = sys.stdin.readline().strip()
            if line in ("1", "2"):
                return line  # type: ignore[return-value]
    if _HAS_MSVCRT:
        while True:
            ch = msvcrt.getch()
            if ch in (b"1", b"2"):
                return ch.decode("ascii")
    if not _HAS_POSIX:
        while True:
            line = sys.stdin.readline().strip()
            if line in ("1", "2"):
                return line  # type: ignore[return-value]
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while True:
            b = sys.stdin.read(1)
            if b in ("1", "2"):
                return b  # type: ignore[return-value]
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def wait_enter_or_esc() -> Literal["enter", "esc"]:
    """Wait for Enter/Return or Escape. On non-TTY, one line read counts as Enter."""
    if not tty_interactive():
        sys.stdin.readline()
        return "enter"
    if _HAS_MSVCRT:
        while True:
            ch = msvcrt.getch()
            if ch == b"\x1b":
                return "esc"
            if ch in (b"\r", b"\n"):
                return "enter"
    if not _HAS_POSIX:
        sys.stdin.readline()
        return "enter"
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while True:
            b = sys.stdin.read(1)
            if not b:
                continue
            o = ord(b)
            if o == 27:
                _drain_escape_suffix()
                return "esc"
            if o in (13, 10):
                return "enter"
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

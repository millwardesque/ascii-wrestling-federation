"""ASCII art and copy for the AWF title screen."""

from __future__ import annotations

# Block-style “AWF” (reads as one logo; fits ~40–48 column terminals)
LOGO_LINES: tuple[str, ...] = (
    " █████╗ ██╗    ██╗███████╗ ",
    " ██╔══██╗██║    ██║██╔════╝ ",
    " ███████║██║ █╗ ██║█████╗  ",
    " ██╔══██║██║███╗██║██╔══╝  ",
    " ██║  ██║╚███╔███╔╝██║     ",
    " ╚═╝  ╚═╝ ╚══╝╚══╝ ╚═╝     ",
)

INTRO_LINES: tuple[str, ...] = (
    "Terminal pro-wrestling — pinfall only.",
    "Pick your fighter, trade holds and strikes, fight until the three-count.",
)

PROMPT_LINE = "Press any key to start"

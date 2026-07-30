"""Hot-reloadable JSON config for prototype tuning values."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _default_config_path() -> Path:
    override = os.environ.get("AWF_CONFIG_PATH")
    if override:
        path = Path(override)
        if not path.is_absolute():
            path = Path(__file__).with_name(override)
        return path
    return Path(__file__).with_name("config.json")


_CONFIG_PATH = _default_config_path()


@dataclass(frozen=True)
class TimingConfig:
    move_gap_between_turns_sec: float = 0.5
    move_log_scroll_delay_sec: float = 1.0
    pin_delay_after_count_1_sec: float = 1.0
    pin_delay_after_count_2_sec: float = 1.5


@dataclass(frozen=True)
class GameConfig:
    timing: TimingConfig = TimingConfig()


_config = GameConfig()
_config_mtime_ns: int | None = None


def _float_value(data: dict[str, Any], key: str, default: float) -> float:
    raw = data.get(key, default)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _load_config(path: Path) -> GameConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return GameConfig()
    timing_data = data.get("timing", {})
    if not isinstance(timing_data, dict):
        timing_data = {}
    default_timing = TimingConfig()
    return GameConfig(
        timing=TimingConfig(
            move_gap_between_turns_sec=_float_value(
                timing_data,
                "move_gap_between_turns_sec",
                default_timing.move_gap_between_turns_sec,
            ),
            move_log_scroll_delay_sec=_float_value(
                timing_data,
                "move_log_scroll_delay_sec",
                default_timing.move_log_scroll_delay_sec,
            ),
            pin_delay_after_count_1_sec=_float_value(
                timing_data,
                "pin_delay_after_count_1_sec",
                default_timing.pin_delay_after_count_1_sec,
            ),
            pin_delay_after_count_2_sec=_float_value(
                timing_data,
                "pin_delay_after_count_2_sec",
                default_timing.pin_delay_after_count_2_sec,
            ),
        )
    )


def get_config() -> GameConfig:
    """Return current config, reloading from disk when ``config.json`` changes.

    Invalid or missing files keep the last good config so mid-match edits cannot crash
    the game loop.
    """
    global _config, _config_mtime_ns
    try:
        mtime_ns = _CONFIG_PATH.stat().st_mtime_ns
    except OSError:
        return _config
    if mtime_ns == _config_mtime_ns:
        return _config
    try:
        loaded = _load_config(_CONFIG_PATH)
    except (OSError, json.JSONDecodeError):
        return _config
    _config = loaded
    _config_mtime_ns = mtime_ns
    return _config

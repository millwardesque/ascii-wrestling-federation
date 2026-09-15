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
class TempoConfig:
    """Turn-queue scheduling. Speed sets how fast a wrestler's next action comes around.

    Delay on the timeline is ``move tempo cost / effective speed``, so a higher speed
    means acting again sooner.
    """

    # Raw roster agility spans 6-15. Used directly as a rate that is a 2.5x action
    # advantage, so compress it: speed = base + (agility - 10) * per_point.
    speed_base: float = 10.0
    speed_per_agility_point: float = 0.35
    # Worn down means slower. Speed is scaled by floor + (1 - floor) * condition fraction,
    # so a wrestler at zero condition still acts, just far less often.
    condition_slow_floor: float = 0.55
    # Position multipliers. Grounded is the big one: it is what creates the cover window.
    grounded_speed_mult: float = 0.60
    corner_speed_mult: float = 0.85
    grappled_speed_mult: float = 0.90
    groggy_speed_mult: float = 0.70
    # Floor so no combination of penalties can stall a wrestler out of the match.
    min_speed: float = 2.0
    # Depth of the projected "next up" strip shown in the UI.
    queue_preview_depth: int = 5


@dataclass(frozen=True)
class GameConfig:
    timing: TimingConfig = TimingConfig()
    tempo: TempoConfig = TempoConfig()


_config = GameConfig()
_config_mtime_ns: int | None = None


def _float_value(data: dict[str, Any], key: str, default: float) -> float:
    raw = data.get(key, default)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _int_value(data: dict[str, Any], key: str, default: int) -> int:
    raw = data.get(key, default)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _section(data: dict[str, Any], key: str) -> dict[str, Any]:
    section = data.get(key, {})
    if not isinstance(section, dict):
        return {}
    return section


def _load_config(path: Path) -> GameConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return GameConfig()
    timing_data = _section(data, "timing")
    tempo_data = _section(data, "tempo")
    default_timing = TimingConfig()
    default_tempo = TempoConfig()
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
        ),
        tempo=TempoConfig(
            speed_base=_float_value(
                tempo_data, "speed_base", default_tempo.speed_base
            ),
            speed_per_agility_point=_float_value(
                tempo_data,
                "speed_per_agility_point",
                default_tempo.speed_per_agility_point,
            ),
            condition_slow_floor=_float_value(
                tempo_data,
                "condition_slow_floor",
                default_tempo.condition_slow_floor,
            ),
            grounded_speed_mult=_float_value(
                tempo_data, "grounded_speed_mult", default_tempo.grounded_speed_mult
            ),
            corner_speed_mult=_float_value(
                tempo_data, "corner_speed_mult", default_tempo.corner_speed_mult
            ),
            grappled_speed_mult=_float_value(
                tempo_data, "grappled_speed_mult", default_tempo.grappled_speed_mult
            ),
            groggy_speed_mult=_float_value(
                tempo_data, "groggy_speed_mult", default_tempo.groggy_speed_mult
            ),
            min_speed=_float_value(
                tempo_data, "min_speed", default_tempo.min_speed
            ),
            queue_preview_depth=_int_value(
                tempo_data, "queue_preview_depth", default_tempo.queue_preview_depth
            ),
        ),
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

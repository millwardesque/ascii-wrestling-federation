"""Layer 1 dialog telemetry: deterministic accuracy checks on match narration.

Fun needs a judge because it has no ground truth. Narration accuracy does have
ground truth: every line the game prints is supposed to describe state changes
the engine already recorded. This module cross-checks the ``log`` text of a
playtest transcript against the ``state`` snapshots in the same transcript, so
factual defects are caught without any LLM judgment.

Findings carry a severity:

- ``error``   — the text asserts something the state contradicts. Hard gate.
- ``warning`` — the text is sloppy, contradictory, or stale. Tracked, not gated.
- ``info``    — the claim cannot be checked because the transcript does not
                expose the field (see ``schema_gaps``). Drives schema work.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from playtest.telemetry import load_transcript_lines  # re-exported for callers
from wrestlers import ROSTER


__all__ = [
    "aggregate_dialog_telemetry",
    "compute_dialog_telemetry",
    "load_transcript_lines",
    "line_template",
    "phrasing_template",
    "DEFAULT_THRESHOLDS",
    "DEFAULT_BATCH_THRESHOLDS",
    "DEFAULT_BANNED_TERMS",
]


# Per-match gates. The variety budgets are ratchets set just outside today's
# worst observed match, not aspirations: they exist to catch regressions. See
# docs/dialog-rubric.md for the targets we actually want to reach.
DEFAULT_THRESHOLDS: dict[str, float] = {
    # Any factual contradiction is a release blocker.
    "max_accuracy_errors": 0,
    # Share of lines that are the bare "Nickname: Move name." fallback.
    "max_flat_line_ratio": 0.55,
    # Distinct phrasings / total lines, after names, numbers and move names are
    # normalised away. Low values mean one sentence shape carries the match.
    "min_phrasing_diversity": 0.05,
    # Same phrasing shape N lines in a row reads as a stuck record.
    "max_consecutive_repeat": 8,
    # Widest single line; the fixed renderer wraps beyond this and the move log
    # only keeps a couple of lines per wrestler.
    "max_line_chars": 110,
}

# Batch gates run against medians across seeds, which is where CI should gate.
DEFAULT_BATCH_THRESHOLDS: dict[str, float] = {
    "max_accuracy_errors": 0,
    "max_median_flat_line_ratio": 0.35,
    "min_median_phrasing_diversity": 0.22,
    "max_median_consecutive_repeat": 4,
}

# Vocabulary CONTEXT.md tells us to avoid in player-facing text. Kept to terms
# that signal engine jargon or a competing mechanic name; deliberately excludes
# ambiguous flavour words like "heat", which the current copy uses on purpose.
DEFAULT_BANNED_TERMS: dict[str, str] = {
    "hp": "condition",
    "hit points": "condition",
    "health points": "condition",
    "life bar": "condition",
    "damage meter": "condition",
    "stunned": "groggy",
    "star power": "charisma",
    "popularity": "charisma",
    "crowd meter": "momentum",
}

_NUMBER_RE = re.compile(r"\d+")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_FLAT_LINE_RE = re.compile(r"^(?P<who>[^:]{1,24}): (?P<what>[^:]+)\.$")
_NO_CONTACT_RE = re.compile(r"whiffs|can't connect|shrugs it off|no contact", re.I)
_DAMAGE_ANYWHERE_RE = re.compile(r"\b(\d+) damage\b")

# Claim patterns keyed by the state they assert about a named wrestler. ``{n}``
# is substituted with the escaped nickname when the checks run.
_GROGGY_TRUE_PATTERNS = (
    r"{n} is GROGGY",
    r"{n} rises — still groggy",
    r"{n} is yanked up",
)
_GROGGY_FALSE_PATTERNS = (
    r"{n} steadies themselves",
    r"{n} fights through — the groggy haze lifts",
)
_GROGGY_PERSIST_PATTERNS = (
    r"{n} tries to clear their head but they're still wobbly",
    r"{n} lunges wildly but can't connect — still groggy",
)
_GROUNDED_PATTERNS = (
    r"{n} collapses to the canvas",
    r"{n} crumples and doesn't move",
    r"{n} tries to rise but can't find it",
)
_KNOCKED_OUT_PATTERNS = (r"{n} crumples and doesn't move — they are out cold",)

# Claims about engine state the transcript schema does not carry. Each entry is
# (pattern, missing transcript field).
_UNVERIFIABLE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"{n} is busted open", "state.bloodied"),
    (r"{n} is rattled — when they're forced up", "state.pending_groggy"),
)
_UNVERIFIABLE_GLOBAL: tuple[tuple[str, str], ...] = (
    (r"The finisher still echoes", "state.pin_bonus_next_cover"),
    (r"the next cover packs extra heat", "state.pin_bonus_next_cover"),
)


def _iter_lines(log: str) -> list[str]:
    return [line.strip() for line in log.splitlines() if line.strip()]


def _first_line(log: str) -> str:
    lines = _iter_lines(log)
    return lines[0] if lines else ""


def line_template(line: str, names: Iterable[str] = ()) -> str:
    """Normalise numbers and wrestler names so surface variety can be counted."""
    out = _NUMBER_RE.sub("N", line)
    for name in sorted(names, key=len, reverse=True):
        if name:
            out = out.replace(name, "{W}")
    return out


def phrasing_template(line: str, names: Iterable[str] = (), moves: Iterable[str] = ()) -> str:
    """``line_template`` plus move names, leaving only the sentence shape.

    Two lines that differ solely by which move landed are the same phrasing, so
    this is the honest measure of how many ways the game can describe a match.
    """
    out = line_template(line, names)
    for move in sorted({m for m in moves if m}, key=len, reverse=True):
        out = re.sub(re.escape(move), "{M}", out, flags=re.I)
    return out


def _match_names(rows: list[dict[str, Any]]) -> tuple[str, str]:
    start = next((row for row in rows if row.get("event") == "match_start"), {})
    ids = list(start.get("wrestlers") or [])
    names: list[str] = []
    for index in range(2):
        wrestler_id = ids[index] if index < len(ids) else ""
        wrestler = ROSTER.get(str(wrestler_id))
        names.append(wrestler.nickname if wrestler else "")
    return names[0], names[1]


def _initial_health(rows: list[dict[str, Any]]) -> list[int] | None:
    """Both wrestlers' starting condition, which is also their ceiling."""
    start = next((row for row in rows if row.get("event") == "match_start"), {})
    ids = list(start.get("wrestlers") or [])
    if len(ids) != 2 or any(str(i) not in ROSTER for i in ids):
        return None
    return [ROSTER[str(i)].max_health for i in ids]


def _claimed_health_delta(log: str, name: str) -> int | None:
    """Damage minus healing that the text attributes to ``name``.

    ``None`` means the text made no numeric claim about this wrestler.
    """
    if not name:
        return None
    escaped = re.escape(name)
    claims: list[int] = []
    # "Hall takes 6 damage." — explicit victim.
    claims += [int(v) for v in re.findall(rf"{escaped} takes (\d+) damage", log)]
    # "Hall reverses the hip toss — only 1 damage" — the reverser eats the chip.
    claims += [
        int(v)
        for v in re.findall(rf"{escaped} reverses the .+? — only (\d+) damage", log)
    ]
    heals = [int(v) for v in re.findall(rf"{escaped} recovers (\d+) stamina", log)]
    if not claims and not heals:
        return None
    return sum(claims) - sum(heals)


def _find(patterns: Iterable[str], log: str, name: str) -> str | None:
    """Return the log line matching any pattern for ``name``, else ``None``."""
    escaped = re.escape(name)
    for pattern in patterns:
        filled = pattern.format(n=escaped)
        for line in _iter_lines(log):
            if re.search(filled, line):
                return line
    return None


def _check_numbers(
    *,
    turn: int,
    log: str,
    names: tuple[str, str],
    before: list[int] | None,
    after: list[int],
    max_health: list[int] | None,
    findings: list[dict[str, Any]],
    checked: list[str],
) -> None:
    if before is None:
        return
    for index, name in enumerate(names):
        if not name:
            continue
        actual = before[index] - after[index]
        claimed = _claimed_health_delta(log, name)
        quote = _find((rf"{{n}}.*\d+ damage", r"{n}.*stamina"), log, name) or _first_line(log)
        if claimed is None:
            if actual != 0:
                findings.append(
                    {
                        "severity": "error",
                        "code": "unnarrated_condition_change",
                        "turn": turn,
                        "line": _first_line(log),
                        "detail": (
                            f"{name} lost {actual} condition with no line describing it"
                        ),
                    }
                )
            continue
        checked.append("condition_delta")
        if claimed == actual:
            continue
        floor_clamped = claimed > actual and after[index] in (0, 1)
        ceiling_clamped = (
            claimed < actual
            and max_health is not None
            and after[index] == max_health[index]
        )
        if floor_clamped or ceiling_clamped:
            findings.append(
                {
                    "severity": "warning",
                    "code": "clamped_number_claim",
                    "turn": turn,
                    "line": quote,
                    "detail": (
                        f"text claims {claimed} against {name} but only {actual} "
                        "was applied after clamping"
                    ),
                }
            )
        elif actual == 0:
            findings.append(
                {
                    "severity": "error",
                    "code": "phantom_damage_claim",
                    "turn": turn,
                    "line": quote,
                    "detail": f"text claims {claimed} damage to {name}; state shows none",
                }
            )
        else:
            findings.append(
                {
                    "severity": "error",
                    "code": "number_mismatch",
                    "turn": turn,
                    "line": quote,
                    "detail": (
                        f"text claims {claimed} against {name}; state shows {actual}"
                    ),
                }
            )


def _check_state_claims(
    *,
    turn: int,
    log: str,
    names: tuple[str, str],
    state: dict[str, Any],
    findings: list[dict[str, Any]],
    checked: list[str],
    schema_gaps: set[str],
) -> None:
    groggy = list(state.get("groggy") or [])
    position = [str(p) for p in (state.get("position") or [])]
    health = list(state.get("health") or [])

    for index, name in enumerate(names):
        if not name:
            continue
        if index < len(groggy):
            quote = _find(_GROGGY_TRUE_PATTERNS, log, name)
            if quote:
                checked.append("groggy")
                if not groggy[index]:
                    findings.append(
                        {
                            "severity": "error",
                            "code": "groggy_claim_unsupported",
                            "turn": turn,
                            "line": quote,
                            "detail": f"text says {name} is groggy; state says not groggy",
                        }
                    )
            quote = _find(_GROGGY_FALSE_PATTERNS, log, name)
            if quote:
                checked.append("groggy")
                if groggy[index]:
                    findings.append(
                        {
                            "severity": "error",
                            "code": "groggy_clear_unsupported",
                            "turn": turn,
                            "line": quote,
                            "detail": f"text says {name} shook it off; state still groggy",
                        }
                    )
            quote = _find(_GROGGY_PERSIST_PATTERNS, log, name)
            if quote and not groggy[index]:
                # A timer can legitimately expire on the same turn the line prints,
                # so this is a readability warning rather than a factual error.
                findings.append(
                    {
                        "severity": "warning",
                        "code": "stale_groggy_claim",
                        "turn": turn,
                        "line": quote,
                        "detail": (
                            f"text says {name} is still wobbly but groggy cleared this turn"
                        ),
                    }
                )
        quote = _find(_GROUNDED_PATTERNS, log, name) if index < len(position) else None
        if quote:
            checked.append("position")
            if position[index] != "GROUNDED":
                findings.append(
                    {
                        "severity": "error",
                        "code": "grounded_claim_unsupported",
                        "turn": turn,
                        "line": quote,
                        "detail": (
                            f"text puts {name} on the mat; state says {position[index]}"
                        ),
                    }
                )
        quote = _find(_KNOCKED_OUT_PATTERNS, log, name) if index < len(health) else None
        if quote:
            checked.append("knockout")
            if health[index] > 0:
                findings.append(
                    {
                        "severity": "error",
                        "code": "knockout_claim_unsupported",
                        "turn": turn,
                        "line": quote,
                        "detail": (
                            f"text calls {name} out cold with {health[index]} condition left"
                        ),
                    }
                )
        for pattern, field in _UNVERIFIABLE_PATTERNS:
            quote = _find((pattern,), log, name)
            if quote:
                schema_gaps.add(field)
                findings.append(
                    {
                        "severity": "info",
                        "code": "unverifiable_claim",
                        "turn": turn,
                        "line": quote,
                        "detail": f"claim needs {field} in the transcript to check",
                    }
                )

    for pattern, field in _UNVERIFIABLE_GLOBAL:
        for line in _iter_lines(log):
            if re.search(pattern, line):
                schema_gaps.add(field)
                findings.append(
                    {
                        "severity": "info",
                        "code": "unverifiable_claim",
                        "turn": turn,
                        "line": line,
                        "detail": f"claim needs {field} in the transcript to check",
                    }
                )
                break


def _check_line_hygiene(
    *,
    turn: int,
    lines: list[str],
    names: tuple[str, str],
    banned_terms: dict[str, str],
    max_line_chars: int,
    findings: list[dict[str, Any]],
) -> int:
    flat = 0
    for line in lines:
        if _ANSI_RE.search(line):
            findings.append(
                {
                    "severity": "error",
                    "code": "ansi_in_transcript",
                    "turn": turn,
                    "line": line,
                    "detail": "escape codes leaked into narration text",
                }
            )
        if "{" in line or "}" in line or "None" in line:
            findings.append(
                {
                    "severity": "error",
                    "code": "template_leak",
                    "turn": turn,
                    "line": line,
                    "detail": "unsubstituted placeholder or None in player-facing text",
                }
            )
        match = _FLAT_LINE_RE.match(line)
        if match and match.group("who") in names:
            flat += 1
        if _DAMAGE_ANYWHERE_RE.search(line) and _NO_CONTACT_RE.search(line):
            findings.append(
                {
                    "severity": "warning",
                    "code": "contradictory_claim",
                    "turn": turn,
                    "line": line,
                    "detail": "one line reports both contact damage and a whiff",
                }
            )
        lowered = line.lower()
        for term, prefer in banned_terms.items():
            if re.search(rf"\b{re.escape(term)}\b", lowered):
                findings.append(
                    {
                        "severity": "warning",
                        "code": "lexicon_violation",
                        "turn": turn,
                        "line": line,
                        "detail": f"'{term}' is reserved vocabulary; say '{prefer}'",
                    }
                )
        if len(line) > max_line_chars:
            findings.append(
                {
                    "severity": "warning",
                    "code": "line_too_long",
                    "turn": turn,
                    "line": line,
                    "detail": f"{len(line)} chars exceeds {max_line_chars}",
                }
            )
    return flat


def _check_silence(
    *,
    turn: int,
    log: str,
    names: tuple[str, str],
    before: dict[str, Any] | None,
    after: dict[str, Any],
    findings: list[dict[str, Any]],
) -> None:
    """A wrestler whose position or groggy flag changed should be mentioned."""
    if before is None:
        return
    for index, name in enumerate(names):
        if not name or name in log:
            continue
        changed: list[str] = []
        for field in ("position", "groggy"):
            old = (before.get(field) or [None, None])[index]
            new = (after.get(field) or [None, None])[index]
            if old != new:
                changed.append(f"{field} {old}->{new}")
        if changed:
            findings.append(
                {
                    "severity": "warning",
                    "code": "silent_state_change",
                    "turn": turn,
                    "line": _first_line(log),
                    "detail": f"{name} changed ({', '.join(changed)}) but is never named",
                }
            )


def compute_dialog_telemetry(
    rows: list[dict[str, Any]],
    *,
    thresholds: dict[str, float] | None = None,
    banned_terms: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Score the narration of one transcript against its own state snapshots."""
    limits = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    terms = DEFAULT_BANNED_TERMS if banned_terms is None else banned_terms
    names = _match_names(rows)
    max_health = _initial_health(rows)

    turns = [row for row in rows if row.get("event") == "turn"]
    findings: list[dict[str, Any]] = []
    checked: list[str] = []
    schema_gaps: set[str] = set()

    all_lines: list[str] = []
    templates: list[str] = []
    phrasings: list[str] = []
    flat_lines = 0

    prev_state: dict[str, Any] | None = None
    prev_health: list[int] | None = _initial_health(rows)

    for row in turns:
        turn = int(row.get("turn") or 0)
        log = str(row.get("log") or "")
        state = dict(row.get("state") or {})
        lines = _iter_lines(log)
        all_lines.extend(lines)
        move = str(row.get("move") or "")
        for line in lines:
            templates.append(line_template(line, names))
            phrasings.append(phrasing_template(line, names, (move,)))

        health_after = [int(v) for v in (state.get("health") or [])]
        if len(health_after) == 2:
            _check_numbers(
                turn=turn,
                log=log,
                names=names,
                before=prev_health,
                after=health_after,
                max_health=max_health,
                findings=findings,
                checked=checked,
            )
        _check_state_claims(
            turn=turn,
            log=log,
            names=names,
            state=state,
            findings=findings,
            checked=checked,
            schema_gaps=schema_gaps,
        )
        flat_lines += _check_line_hygiene(
            turn=turn,
            lines=lines,
            names=names,
            banned_terms=terms,
            max_line_chars=int(limits["max_line_chars"]),
            findings=findings,
        )
        _check_silence(
            turn=turn,
            log=log,
            names=names,
            before=prev_state,
            after=state,
            findings=findings,
        )
        for nickname in _foreign_nicknames(log, names):
            findings.append(
                {
                    "severity": "error",
                    "code": "foreign_wrestler_named",
                    "turn": turn,
                    "line": next(
                        (line for line in _iter_lines(log) if nickname in line),
                        _first_line(log),
                    ),
                    "detail": f"'{nickname}' is not in this match",
                }
            )

        prev_state = state
        if len(health_after) == 2:
            prev_health = health_after

    line_count = len(all_lines)
    unique_lines = len(set(templates))
    phrasing_count = len(set(phrasings))
    top_phrasing_share = 0.0
    if phrasings:
        top_phrasing_share = max(
            phrasings.count(p) for p in set(phrasings)
        ) / len(phrasings)

    errors = [f for f in findings if f["severity"] == "error"]
    warnings = [f for f in findings if f["severity"] == "warning"]
    infos = [f for f in findings if f["severity"] == "info"]

    variety = {
        "line_count": line_count,
        "unique_line_ratio": _ratio(unique_lines, line_count),
        "phrasing_template_count": phrasing_count,
        "phrasing_diversity": _ratio(phrasing_count, line_count),
        "top_phrasing_share": round(top_phrasing_share, 4),
        "max_consecutive_repeat": _max_run(phrasings),
        "flat_line_ratio": _ratio(flat_lines, line_count),
    }
    readability = {
        "max_line_chars": max((len(line) for line in all_lines), default=0),
        "avg_line_chars": _ratio(
            sum(len(line) for line in all_lines), line_count, digits=1
        ),
        "over_width_lines": sum(
            1 for f in findings if f["code"] == "line_too_long"
        ),
    }
    accuracy = {
        "checked_claims": len(checked),
        "claims_by_kind": {kind: checked.count(kind) for kind in sorted(set(checked))},
        "errors": len(errors),
        "warnings": len(warnings),
        "unverifiable_claims": len(infos),
        "claim_verifiability_ratio": _ratio(
            len(checked), len(checked) + len(infos)
        ),
        "schema_gaps": sorted(schema_gaps),
    }

    gate_failures = _gate_failures(
        limits=limits, accuracy=accuracy, variety=variety, readability=readability
    )
    start = next((row for row in rows if row.get("event") == "match_start"), {})
    return {
        "gates_passed": not gate_failures,
        "gate_failures": gate_failures,
        "match_seed": start.get("match_seed"),
        "wrestlers": start.get("wrestlers"),
        "player_policy": start.get("player_policy"),
        "turn_count": len(turns),
        "accuracy": accuracy,
        "variety": variety,
        "readability": readability,
        "findings": findings,
    }


def aggregate_dialog_telemetry(
    reports: Iterable[dict[str, Any]],
    *,
    thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Roll per-match dialog telemetry into one batch verdict.

    Per-match numbers are noisy because a short match can be carried by three
    lines. Gate on the batch: accuracy errors anywhere fail, and the variety
    budgets are checked against medians across seeds.
    """
    limits = {**DEFAULT_BATCH_THRESHOLDS, **(thresholds or {})}
    batch = [dict(report) for report in reports]
    if not batch:
        return {
            "gates_passed": False,
            "gate_failures": ["no dialog telemetry reports supplied"],
            "match_count": 0,
        }

    def values(section: str, key: str) -> list[float]:
        return [float(report.get(section, {}).get(key, 0)) for report in batch]

    def worst(section: str, key: str, *, highest: bool) -> dict[str, Any]:
        chooser = max if highest else min
        pick = chooser(batch, key=lambda r: float(r.get(section, {}).get(key, 0)))
        return {
            "match_seed": pick.get("match_seed"),
            "value": pick.get(section, {}).get(key),
        }

    finding_counts: dict[str, int] = {}
    examples: dict[str, dict[str, Any]] = {}
    schema_gaps: set[str] = set()
    error_seeds: list[Any] = []
    for report in batch:
        for finding in report.get("findings", []):
            code = str(finding.get("code"))
            finding_counts[code] = finding_counts.get(code, 0) + 1
            examples.setdefault(
                code, {"match_seed": report.get("match_seed"), **finding}
            )
        schema_gaps.update(report.get("accuracy", {}).get("schema_gaps", []))
        if report.get("accuracy", {}).get("errors", 0):
            error_seeds.append(report.get("match_seed"))

    medians = {
        "flat_line_ratio": _median(values("variety", "flat_line_ratio")),
        "phrasing_diversity": _median(values("variety", "phrasing_diversity")),
        "top_phrasing_share": _median(values("variety", "top_phrasing_share")),
        "max_consecutive_repeat": _median(values("variety", "max_consecutive_repeat")),
        "unique_line_ratio": _median(values("variety", "unique_line_ratio")),
    }

    gate_failures: list[str] = []
    total_errors = int(sum(values("accuracy", "errors")))
    if total_errors > limits["max_accuracy_errors"]:
        gate_failures.append(
            f"{total_errors} accuracy errors across seeds {sorted(map(str, error_seeds))}"
        )
    if medians["flat_line_ratio"] > limits["max_median_flat_line_ratio"]:
        gate_failures.append(
            f"median flat_line_ratio {medians['flat_line_ratio']} exceeds "
            f"{limits['max_median_flat_line_ratio']}"
        )
    if medians["phrasing_diversity"] < limits["min_median_phrasing_diversity"]:
        gate_failures.append(
            f"median phrasing_diversity {medians['phrasing_diversity']} below "
            f"{limits['min_median_phrasing_diversity']}"
        )
    if medians["max_consecutive_repeat"] > limits["max_median_consecutive_repeat"]:
        gate_failures.append(
            f"median max_consecutive_repeat {medians['max_consecutive_repeat']} exceeds "
            f"{limits['max_median_consecutive_repeat']}"
        )

    return {
        "gates_passed": not gate_failures,
        "gate_failures": gate_failures,
        "match_count": len(batch),
        "accuracy_errors_total": total_errors,
        "matches_with_accuracy_errors": len(error_seeds),
        "medians": medians,
        "worst": {
            "flat_line_ratio": worst("variety", "flat_line_ratio", highest=True),
            "phrasing_diversity": worst("variety", "phrasing_diversity", highest=False),
            "max_consecutive_repeat": worst(
                "variety", "max_consecutive_repeat", highest=True
            ),
            "max_line_chars": worst("readability", "max_line_chars", highest=True),
        },
        "finding_counts": dict(sorted(finding_counts.items(), key=lambda kv: -kv[1])),
        "finding_examples": examples,
        "schema_gaps": sorted(schema_gaps),
    }


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[middle], 4)
    return round((ordered[middle - 1] + ordered[middle]) / 2, 4)


def _foreign_nicknames(log: str, names: tuple[str, str]) -> list[str]:
    out: list[str] = []
    for wrestler in ROSTER.values():
        nickname = wrestler.nickname
        if nickname in names:
            continue
        if any(nickname in name or name in nickname for name in names if name):
            continue
        if re.search(rf"\b{re.escape(nickname)}\b", log):
            out.append(nickname)
    return sorted(set(out))


def _ratio(part: float, whole: float, *, digits: int = 4) -> float:
    if not whole:
        return 0.0
    return round(part / whole, digits)


def _max_run(values: list[str]) -> int:
    best = 0
    run = 0
    previous: str | None = None
    for value in values:
        run = run + 1 if value == previous else 1
        previous = value
        best = max(best, run)
    return best


def _gate_failures(
    *,
    limits: dict[str, float],
    accuracy: dict[str, Any],
    variety: dict[str, Any],
    readability: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    if accuracy["errors"] > limits["max_accuracy_errors"]:
        failures.append(
            f"{accuracy['errors']} narration claims contradict match state"
        )
    if variety["flat_line_ratio"] > limits["max_flat_line_ratio"]:
        failures.append(
            f"flat_line_ratio {variety['flat_line_ratio']} exceeds "
            f"{limits['max_flat_line_ratio']}"
        )
    if variety["line_count"] and variety["phrasing_diversity"] < limits[
        "min_phrasing_diversity"
    ]:
        failures.append(
            f"phrasing_diversity {variety['phrasing_diversity']} below "
            f"{limits['min_phrasing_diversity']}"
        )
    if variety["max_consecutive_repeat"] > limits["max_consecutive_repeat"]:
        failures.append(
            f"same phrasing repeated {variety['max_consecutive_repeat']} lines in a row"
        )
    return failures

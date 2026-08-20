"""Commentary engine — renders ``MatchEvent`` facts into booth lines.

Play-by-play names the action; color reacts. Template pools are keyed by
commentator id with role-level fallbacks. Catchphrases are rare garnish.

See ``docs/commentary-design.md``.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Sequence

from commentators import Commentator, CommentatorPair, ROSTER as COMMENTATORS
from commentary_events import CommentaryLine, EventKind, MatchEvent, format_commentary_line
from commentary_templates import move_commentary_pool, outcome_for_event_kind
from wrestlers import Wrestler

if TYPE_CHECKING:
    from game import PinSequence


# Highest-stakes kinds first — one PBP line is chosen from the top event.
_KIND_PRIORITY: tuple[EventKind, ...] = (
    "knockout",
    "pinfall",
    "submission_tap",
    "submission_escape",
    "pin_kickout",
    "pin_count",
    "submission_applied",
    "knockdown",
    "groggy_applied",
    "bloodied",
    "reversal",
    "miss",
    "damage",
    "groggy_cleared",
    "recover",
    "loop_pressure",
    "setup",
    "position_change",
    "move_attempt",
    "momentum_shift",
)

_ALWAYS_COLOR: frozenset[str] = frozenset(
    {
        "reversal",
        "miss",
        "knockdown",
        "knockout",
        "pin_kickout",
        "pinfall",
        "submission_tap",
        "submission_escape",
        "groggy_applied",
        "bloodied",
    }
)
_NEVER_COLOR: frozenset[str] = frozenset({"pin_count"})
_CALL_KINDS: tuple[EventKind, ...] = (
    "knockout",
    "pinfall",
    "submission_tap",
    "submission_escape",
    "pin_kickout",
    "pin_count",
    "submission_applied",
    "reversal",
    "miss",
    "damage",
    "groggy_cleared",
    "recover",
    "setup",
    "position_change",
    "move_attempt",
)
_REACTION_KINDS: frozenset[str] = frozenset(
    {"groggy_applied", "bloodied", "knockdown", "loop_pressure"}
)

# Role-level fallbacks. Per-id overlays in ``_ID_TEMPLATES`` win when present.
_ROLE_TEMPLATES: dict[tuple[str, EventKind], tuple[str, ...]] = {
    ("pbp", "damage"): (
        "{actor} with the {move} — {target} felt that one!",
        "{actor} hits the {move}! {target} is hurting!",
        "There's the {move} from {actor}!",
    ),
    ("pbp", "miss"): (
        "{actor} goes for the {move} — no luck!",
        "{target} gets out of the way — {actor} misses!",
        "{actor} can't find {target} with that {move}!",
    ),
    ("pbp", "reversal"): (
        "{target} reverses the {move}!",
        "{target} turns it around — {actor} eats their own {move}!",
        "Counter by {target}! The {move} backfires!",
    ),
    ("pbp", "setup"): (
        "{actor} with the {move}!",
        "{actor} looking for the {move} — there it is!",
        "{move} from {actor}.",
    ),
    ("pbp", "position_change"): (
        "{actor} with the {move}!",
        "{actor} changes the geography with a {move}!",
    ),
    ("pbp", "move_attempt"): (
        "{actor} with the {move}!",
        "{actor} going for the {move}!",
    ),
    ("pbp", "groggy_applied"): (
        "{target} is out on their feet!",
        "{target} is wobbly — that one's got 'em!",
        "{target} doesn't know where they are!",
    ),
    ("pbp", "groggy_cleared"): (
        "{actor} shakes it off — they're back!",
        "{actor} finds their legs!",
    ),
    ("pbp", "knockdown"): (
        "{target} down on the canvas!",
        "{target} collapses — they're on the mat!",
        "Down goes {target}!",
    ),
    ("pbp", "knockout"): (
        "{target} is out cold! This one's over!",
        "{actor} knocks {target} out — the referee waves it off!",
    ),
    ("pbp", "bloodied"): (
        "{target} is busted open!",
        "The crimson's flowing — {target} is cut!",
    ),
    ("pbp", "recover"): (
        "{actor} catching a breath.",
        "{actor} trying to recover in there.",
    ),
    ("pbp", "loop_pressure"): (
        "We've seen this {move} a few too many times.",
        "The crowd's getting restless with this {move}.",
    ),
    ("pbp", "pin_count"): (
        "{count_word}!",
        "That's {count_word}!",
    ),
    ("pbp", "pin_kickout"): (
        "{target} kicks out!",
        "No! {target} gets the shoulder up!",
        "{target} kicks out — this crowd is alive!",
    ),
    ("pbp", "pinfall"): (
        "Three! {actor} wins it!",
        "That's it — pinfall! {actor} wins!",
    ),
    ("pbp", "submission_applied"): (
        "{actor} hooks in the {move}!",
        "There's the {move} — {target} is in trouble!",
    ),
    ("pbp", "submission_escape"): (
        "{target} claws free and breaks the hold!",
        "{target} reaches the ropes — no, they fight out of the {move}!",
    ),
    ("pbp", "submission_tap"): (
        "{target} taps out! {actor} wins it!",
        "That's it — {target} gives up! {actor} wins!",
    ),
    ("pbp", "momentum_shift"): (
        "The momentum is swinging!",
    ),
    ("color", "damage"): (
        "That's gonna leave a mark.",
        "{target} didn't like that one bit.",
        "Keep it coming!",
    ),
    ("color", "miss"): (
        "What was that supposed to be?",
        "{actor} looked lost on that one.",
        "Somebody's gotta start wrestling.",
    ),
    ("color", "reversal"): (
        "That's how you do it, {target}!",
        "{actor} walked right into that.",
        "I love a good counter.",
    ),
    ("color", "setup"): (
        "I see what {actor}'s doing.",
        "Don't give {actor} that much room.",
    ),
    ("color", "position_change"): (
        "Now we're getting somewhere.",
    ),
    ("color", "move_attempt"): (
        "Here we go.",
    ),
    ("color", "groggy_applied"): (
        "{target} is in dreamland — finish it!",
        "That's the opening. Don't waste it.",
    ),
    ("color", "groggy_cleared"): (
        "I thought they were done.",
        "This one's got heart, I'll give 'em that.",
    ),
    ("color", "knockdown"): (
        "Cover! Cover!",
        "They're not getting up from that.",
    ),
    ("color", "knockout"): (
        "Somebody get a doctor — and a winner.",
        "That's a wrap. Night-night.",
    ),
    ("color", "bloodied"): (
        "Look at that — that's a war paint.",
        "The hard way to make a living.",
    ),
    ("color", "recover"): (
        "Rest while you can.",
        "The crowd's not here for a nap.",
    ),
    ("color", "loop_pressure"): (
        "Do something else already!",
        "I've seen this match before.",
    ),
    ("color", "pin_kickout"): (
        "This crowd is going wild!",
        "I don't believe it!",
        "How did {target} kick out of that?!",
    ),
    ("color", "pinfall"): (
        "That's a winner!",
        "Hand it to {actor} — they earned it.",
    ),
    ("color", "submission_applied"): (
        "That's not coming off.",
        "{target} better tap before something snaps.",
    ),
    ("color", "submission_escape"): (
        "Not tonight!",
        "{target} wasn't ready to quit.",
    ),
    ("color", "submission_tap"): (
        "Smart. Live to fight another day.",
        "When it's that tight, you tap.",
    ),
    ("color", "momentum_shift"): (
        "Now that's a swing.",
    ),
    ("color", "pin_count"): (
        "",
    ),
}

_ID_TEMPLATES: dict[tuple[str, EventKind], tuple[str, ...]] = {
    ("gorilla", "damage"): (
        "{actor} with a {move} — what a maneuver!",
        "{actor} plants {target} with that {move}!",
        "Will you look at that {move} from {actor}!",
    ),
    ("gorilla", "pin_count"): (
        "{count_word}!",
        "The count — {count_word}!",
    ),
    ("gorilla", "pin_kickout"): (
        "{target} kicks out! Will you look at that!",
        "No sir — {target} gets the shoulder up!",
    ),
    ("gorilla", "pinfall"): (
        "Three! {actor} is the winner!",
        "That's it — a pinfall for {actor}!",
    ),
    ("ross", "damage"): (
        "{actor} with a {move}! {target} is in a world of hurt!",
        "BAWOOO — {move} by {actor}!",
        "{actor} lights up {target} with that {move}!",
    ),
    ("ross", "pin_count"): (
        "{count_word}!",
        "THAT'S {count_word}!",
    ),
    ("ross", "pin_kickout"): (
        "{target} kicked out! This is a slobberknocker!",
        "NO SIR! {target} will not stay down!",
    ),
    ("ross", "pinfall"): (
        "THREE! {actor} wins it, business is concluded!",
        "That's it — {actor} just won a whale of a match!",
    ),
    ("ventura", "damage"): (
        "That's the smart money, {actor}.",
        "{target} can think about that one in the locker room.",
    ),
    ("ventura", "reversal"): (
        "Conspiracy? That's just good wrestling, {target}.",
        "You don't get paid to think, {actor} — you get paid to eat that.",
    ),
    ("ventura", "pin_kickout"): (
        "Booked to go longer. I knew it.",
        "Nobody stays down when the check's that big.",
    ),
    ("heenan", "damage"): (
        "Give me a break — {target} asked for that.",
        "The Brain saw that {move} coming a mile away.",
    ),
    ("heenan", "miss"): (
        "What an idiot! {actor} can't hit a barn door.",
        "Give me a break — that was embarrassing.",
    ),
    ("heenan", "pin_kickout"): (
        "I told you {target} wasn't done! The Brain knows!",
        "Give me a break — they're never gonna pin {target}!",
    ),
    ("lawler", "damage"): (
        "That's a classic {move}! The crowd loves it!",
        "{target} is hurting — this Memphis crowd would eat that up!",
    ),
    ("lawler", "pin_kickout"): (
        "That's a classic kickout! This crowd is hot!",
        "Memphis would've eaten that up — {target} kicked out!",
    ),
    ("cornette", "damage"): (
        "That's how you wrestle, {actor}!",
        "Oh come on — {target} walked right into that {move}!",
    ),
    ("cornette", "miss"): (
        "This is an outrage — {actor} looked like an amateur!",
        "Oh come on! Hit somebody!",
    ),
    ("cornette", "pin_kickout"): (
        "Oh come on! How did {target} kick out?!",
        "This is an outrage — they had {target} beat!",
    ),
}

_COUNT_WORDS = {1: "one", 2: "two", 3: "three"}


class CommentaryEngine:
    def __init__(self, team: CommentatorPair, seed: int | None = None) -> None:
        self._team = team
        self._rng = random.Random(0 if seed is None else seed)
        self._catchphrase_used: set[str] = set()

    @property
    def team(self) -> CommentatorPair:
        return self._team

    def speaker_short(self, line: CommentaryLine) -> str:
        return COMMENTATORS[line.speaker_id].short

    def booth_intro_lines(self) -> tuple[CommentaryLine, ...]:
        """Lines shown when the bell rings."""
        pbp = self._team.pbp()
        color = self._team.color()
        return (
            CommentaryLine(
                speaker_id=pbp.id,
                role="pbp",
                text=f"{pbp.name} here with {color.name} — let's get this one underway!",
            ),
            CommentaryLine(
                speaker_id=color.id,
                role="color",
                text="I've got a feeling somebody's walking out unhappy.",
            ),
        )

    def format_lines(
        self,
        events: Sequence[MatchEvent],
        wrestlers: tuple[Wrestler, Wrestler],
        *,
        actor_idx: int | None = None,
        move_name: str | None = None,
    ) -> list[str]:
        """Move-log strings: ``  GORILLA: …``."""
        return [
            f"  {format_commentary_line(line, roster_short=self.speaker_short(line))}"
            for line in self.render_turn(
                events, wrestlers=wrestlers, actor_idx=actor_idx, move_name=move_name
            )
        ]

    def format_turn(
        self,
        events: Sequence[MatchEvent],
        wrestlers: tuple[Wrestler, Wrestler],
        *,
        actor_idx: int | None = None,
        move_name: str | None = None,
    ) -> str:
        return "\n".join(
            self.format_lines(
                events, wrestlers, actor_idx=actor_idx, move_name=move_name
            )
        )

    def commentate_sequence(
        self,
        sequence: PinSequence,
        wrestlers: tuple[Wrestler, Wrestler],
    ) -> PinSequence:
        """Rewrite pin/submission steps as booth lines; keep timing."""
        from game import PinSequence as PinSeq

        preamble = (
            self.format_lines(sequence.preamble_events, wrestlers)
            if sequence.preamble_events
            else list(sequence.preamble_lines)
        )
        steps: list[tuple[list[str], float]] = []
        for i, (legacy, delay) in enumerate(sequence.steps):
            evs = sequence.step_events[i] if i < len(sequence.step_events) else []
            steps.append(
                (self.format_lines(evs, wrestlers) if evs else list(legacy), delay)
            )
        return PinSeq(
            won=sequence.won,
            preamble_lines=preamble,
            steps=steps,
            heading=sequence.heading,
            preamble_events=list(sequence.preamble_events),
            step_events=[list(evs) for evs in sequence.step_events],
        )

    def render_turn(
        self,
        events: Sequence[MatchEvent],
        *,
        wrestlers: tuple[Wrestler, Wrestler],
        actor_idx: int | None = None,
        move_name: str | None = None,
    ) -> list[CommentaryLine]:
        """Map events to alternating PBP/color lines for one turn or pin step."""
        pbp = self._team.pbp()
        color = self._team.color()
        facts = self._facts(events, wrestlers, actor_idx, move_name)
        kinds = [e.kind for e in events]
        primary = self._primary_kind(kinds)
        if primary is None:
            primary = "setup"
        call = self._call_kind(kinds)

        lines: list[CommentaryLine] = []
        spoken: set[str] = set()
        if call is not None and call != primary:
            lines.append(
                CommentaryLine(
                    speaker_id=pbp.id,
                    role="pbp",
                    text=self._pick_line(pbp, call, facts),
                )
            )
            spoken.add(call)
        lines.append(
            CommentaryLine(
                speaker_id=pbp.id,
                role="pbp",
                text=self._pick_line(pbp, primary, facts),
            )
        )
        spoken.add(primary)

        for kind in kinds:
            if kind in _REACTION_KINDS and kind not in spoken:
                lines.append(
                    CommentaryLine(
                        speaker_id=pbp.id,
                        role="pbp",
                        text=self._pick_line(pbp, kind, facts),
                    )
                )
                spoken.add(kind)
                break

        dive_actor = actor_idx
        for event in events:
            if event.kind in {"miss", "reversal"} and event.actor is not None:
                dive_actor = event.actor
                break
        crashed_off_top = any(
            event.kind == "position_change"
            and event.position == "GROUNDED"
            and event.actor == dive_actor
            for event in events
        )
        if primary in {"miss", "reversal"} and crashed_off_top:
            lines.append(
                CommentaryLine(
                    speaker_id=pbp.id,
                    role="pbp",
                    text=self._rng.choice(
                        (
                            f"{facts['actor']} crashes off the top to the canvas!",
                            f"{facts['actor']} comes down hard off the buckle!",
                        )
                    ),
                )
            )

        if self._color_speaks(primary):
            catch = self._maybe_catchphrase(color)
            text = catch if catch else self._pick_line(color, primary, facts)
            if text.strip():
                lines.append(
                    CommentaryLine(speaker_id=color.id, role="color", text=text)
                )
        return lines

    def _primary_kind(self, kinds: Sequence[str]) -> EventKind | None:
        present = set(kinds)
        for kind in _KIND_PRIORITY:
            if kind in present:
                return kind
        return None

    def _call_kind(self, kinds: Sequence[str]) -> EventKind | None:
        present = set(kinds)
        for kind in _CALL_KINDS:
            if kind in present:
                return kind
        return None

    def _color_speaks(self, kind: str) -> bool:
        if kind in _NEVER_COLOR:
            return False
        if kind in _ALWAYS_COLOR:
            return True
        return self._rng.random() < 0.5

    def _maybe_catchphrase(self, commentator: Commentator) -> str | None:
        if not commentator.catchphrases:
            return None
        if commentator.id in self._catchphrase_used:
            return None
        if self._rng.random() > 0.08:
            return None
        self._catchphrase_used.add(commentator.id)
        return self._rng.choice(commentator.catchphrases)

    def _pick_line(
        self,
        commentator: Commentator,
        kind: EventKind,
        facts: dict[str, str],
    ) -> str:
        outcome = outcome_for_event_kind(kind)
        if outcome is not None:
            move_pool = move_commentary_pool(
                facts.get("move_id"), commentator.id, outcome
            )
            if move_pool:
                return self._rng.choice(move_pool).format(**facts)
        pool = _ID_TEMPLATES.get((commentator.id, kind)) or _ROLE_TEMPLATES.get(
            (commentator.role, kind)
        )
        if not pool:
            pool = ("{actor} with the {move}!",)
        template = self._rng.choice(pool)
        return template.format(**facts)

    def _facts(
        self,
        events: Sequence[MatchEvent],
        wrestlers: tuple[Wrestler, Wrestler],
        actor_idx: int | None,
        move_name: str | None,
    ) -> dict[str, str]:
        actor_i = actor_idx
        target_i: int | None = None
        move = move_name or ""
        move_id = ""
        pin_count: int | None = None
        for event in events:
            if event.actor is not None:
                actor_i = event.actor
            if event.target is not None:
                target_i = event.target
            if event.move_name:
                move = event.move_name
            if event.move_id:
                move_id = event.move_id
            if event.pin_count is not None:
                pin_count = event.pin_count
        if target_i is None and actor_i is not None:
            target_i = 1 - actor_i
        actor_w = wrestlers[actor_i] if actor_i is not None else None
        target_w = wrestlers[target_i] if target_i is not None else None
        actor = actor_w.nickname if actor_w is not None else "they"
        target = target_w.nickname if target_w is not None else "them"
        count_word = _COUNT_WORDS.get(pin_count or 0, "one")
        return {
            "actor": actor,
            "target": target,
            "actor_name": actor_w.name if actor_w is not None else actor,
            "target_name": target_w.name if target_w is not None else target,
            "move": move.lower() if move else "that one",
            "move_id": move_id,
            "count_word": count_word,
        }

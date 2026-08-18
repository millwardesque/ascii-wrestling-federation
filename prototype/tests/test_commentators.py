"""Tests for commentary booth roster and pair selection."""

from __future__ import annotations

import unittest

from commentators import (
    CURATED_PAIRS,
    ROSTER,
    choose_commentary_team,
    validate_roster,
)


class TestCommentatorRoster(unittest.TestCase):
    def test_curated_pairs_are_valid(self) -> None:
        validate_roster()

    def test_every_pair_has_pbp_and_color(self) -> None:
        for pair in CURATED_PAIRS:
            self.assertEqual(pair.pbp().role, "pbp")
            self.assertEqual(pair.color().role, "color")
            self.assertNotEqual(pair.pbp_id, pair.color_id)

    def test_all_roster_ids_are_unique(self) -> None:
        self.assertEqual(len(ROSTER), len({c.id for c in ROSTER.values()}))


class TestChooseCommentaryTeam(unittest.TestCase):
    def test_same_seed_same_pair(self) -> None:
        a = choose_commentary_team(4242)
        b = choose_commentary_team(4242)
        self.assertEqual(a.ids, b.ids)

    def test_different_seeds_can_differ(self) -> None:
        pairs = {choose_commentary_team(seed).ids for seed in range(200)}
        self.assertGreater(len(pairs), 1)

    def test_label_and_intro(self) -> None:
        pair = choose_commentary_team(1)
        self.assertIn("&", pair.label())
        self.assertTrue(pair.intro_line().startswith("On the call:"))


if __name__ == "__main__":
    unittest.main()

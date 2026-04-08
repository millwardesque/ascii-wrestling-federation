"""Every (actor, target) body position pair must allow at least one move."""

from __future__ import annotations

import unittest
from itertools import product

from game import MatchState
from moves import BodyPosition
from wrestlers import ROSTER


class TestPositionPairCoverage(unittest.TestCase):
    def test_each_actor_target_pair_has_a_move(self) -> None:
        w1, w2 = ROSTER["bret_hart"], ROSTER["cm_punk"]
        for actor_pos, target_pos in product(BodyPosition, BodyPosition):
            ok = False
            for rebound in (False, True):
                st = MatchState(wrestlers=(w1, w2))
                st.position[0] = actor_pos
                st.position[1] = target_pos
                st.rebound[0] = rebound
                if st.valid_rules(0):
                    ok = True
                    break
            self.assertTrue(
                ok,
                f"No valid move for actor={actor_pos!r} target={target_pos!r}",
            )


if __name__ == "__main__":
    unittest.main()

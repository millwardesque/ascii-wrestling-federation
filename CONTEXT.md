# Match

Turn-based pro wrestling match simulation. Two wrestlers trade moves until one wins by pinfall or submission.

## Language

**Momentum**:
Ring control — how much command a wrestler currently has over the match, blending physical rhythm, position dominance, and crowd response. Gates finishers and makes offense land more reliably as it rises.
_Avoid_: heat, confidence, crowd meter (as separate concepts)

**Charisma**:
A wrestler's ability to convert successful offense into momentum — crowd connection and presence that amplifies ring control when moves land.
_Avoid_: popularity, star power

**Groggy**:
Stunned on your feet — wobbly, exploitable, and open to groggy-gated finishers. Clears after a short opponent-action window, damage, or a shake-off.
_Avoid_: stunned (as a separate state)

**Pending groggy**:
Groggy queued while grounded — pays off when the victim next stands after a slam or similar.
_Avoid_: delayed stun

**Finisher shock**:
Lingering beatdown from eating a finisher — makes fighting to your feet harder until you successfully stand. Not a stun window.
_Avoid_: groggy, stunned

**Condition**:
Accumulated wear from offense taken — how beaten up a wrestler is. Never removes them from the match, but makes them easier to hit, harder to kick out, and slower to recover. Stored as health points internally.
_Avoid_: HP, life, damage meter (as knockout)

**Running the ropes**:
A ring position where the wrestler is sprinting the ropes — gates rope-sprint offense and counter opportunities while the opponent is in the same state.
_Avoid_: rebound (as a separate setup flag)

**Tactical intent**:
Player-facing labels that group legal moves into readable choices (Finish, Big swing, Grapple control, etc.). Derived at display time from move properties; not part of match rules.
_Avoid_: move category (in engine code)

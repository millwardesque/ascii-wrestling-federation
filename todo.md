# TODO

## Recently completed

- **Random seed per match** — `secrets.randbits(63)` and `random.seed()` at match start; seed shown in the fixed-layout match header (scroll UI removed).
- **Fixed layout default** — `FixedLayoutRenderer` only; legacy scroll renderer deleted (`--scroll` removed).
- **No exhaustion draw** — Damage floors HP at 1; matches end by pinfall only; double-exhaustion path removed.

## Product direction

- Remove stick figures and animations
- Add an “AWF (ASCII Wrestling Federation)” start screen
- Pause menu (e.g. ESC) with option to return to the start screen
- Hide the round number; remove from UI and from code unless still required internally

## Backlog

### Gameplay & rules

- Submissions
- Weapons
- Fight on the floor
- Stunned state
- Per-wrestler movesets
- Tag-team matches

### Roster & meta

- Managers
- Teams

### Platform & architecture

- Investigate porting to Electrobun
- Document API seams / game modules (e.g. renderer, CPU AI, game logic) for different systems to use in production-ready version

### Content & polish

- Change UX for move output and outcomes to be more like a two-man commentary team (like Jerry Lawler and Jim Ross, Gorilla Monsoon and Bobby Heenan, etc.)
- Save replay (and random seed value) to file

### Documentation

- Document algorithms

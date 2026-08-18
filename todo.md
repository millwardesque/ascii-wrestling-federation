# TODO

## Backlog

### Gameplay & rules

- Weapons
- Fight on the floor
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

### Dialog quality (see `docs/dialog-eval-design.md`)

- Narration coverage harness: force every narration site from pinned state + RNG
- Replace `Nickname: Move name.` fallback lines with real narration (baseline median 31% of lines)
- Stop claiming damage that clamping never applied
- Split the reverse-and-whiff line that reports contact and a miss at once
- Batch automation template for dialog judging (mirror `.cursor/automations/playtest-batch.md`)
- Return structured events from `apply_move` so narration renders from facts

### Documentation

- Document algorithms

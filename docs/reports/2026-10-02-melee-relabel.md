# Melee historical cleanup -- 2026-10-02

Live DB writes, each in its own transaction after a fresh backup and an integrity check, each
re-verified afterwards. Aggregate figures only: no player names and no match row ids (those live in
the manifests and evidence beside the DB, `E:\mtg-data\reports\melee_relabel\` and
`E:\mtg-data\raw\melee_relabel\`, which are not in git).

## Why

Until 00a4f54 the Melee scraper called `normalize(deck_name, fmt)`, which put the format string into
normalize's positional `fuzzy` flag. Every Melee label stored since the pipeline began (98dd83c,
2026-03-21) was therefore fuzzy-guessed: for example 'Mono-Green Broodscale' became 'Mono Red Aggro'. The
published deck names were never stored, so they were recovered by re-reading all 912 events' pairings
(0 failed rounds).

## 1. Format correction, mtgmelee_391510 (rounds 1-3 Standard, 4-6 Pauper per the event page)

| | rows |
|---|---:|
| standard -> pauper (rounds 4-6) | 47 |
| pauper -> standard (rounds 1-3) | 3 |

Only `format` changed. Total rows unchanged; integrity ok; re-run 0.
Backup: `mtg_meta.backup-2026-10-02-pre-melee-format-fix.db`.

## 2. Trios events: per-pairing format correction (NOT quarantined)

Melee's pairing data for the five trios events lists **1v1 seat matches with a per-match Format**.
They are valid observations. An earlier claim that these rows were team results was wrong and has been
corrected in the survey report. A row was re-tagged only if it joined exactly one 1v1 pairing on
(round, player1, player2) and the pairing's game result equalled the stored result. There were 0
disagreements.

| move | rows |
|---|---:|
| standard -> modern | 177 |
| legacy -> vintage | 155 |
| modern -> legacy | 97 |
| legacy -> modern | 6 |
| modern -> vintage | 4 |
| pioneer -> modern | 3 |
| pioneer -> standard | 1 |
| **total changed** | **443** |
| already correct | 93 |
| held (no pairing joins; mtgmelee_437430) | 6 |

The 542 rows reconcile as 443 changed + 93 already correct + 6 held. 159 rows are now `vintage`: they
stay in `matches` and are outside the five per-format views. "All formats" views apply no format filter,
so they include those rows, as they include any format. Integrity ok, re-run 0.
Backup: `mtg_meta.backup-2026-10-02-pre-team-format-fix.db`.

## 3. Limited rows quarantined (150)

Draft/Sealed rounds of 10 mixed events (Pro Tours, Worlds, nationals), proven per round: every pairing
of the round has a Draft/Sealed match Format. That is 147 rows in Swiss rounds, plus 3 in Pro Tour Marvel's
Draft top 8. Of the 150, 3 rows do not join a pairing by player name; they are proven by their round.

- Moved unchanged, with their original ids, to `matches_excluded`. Reason `limited-round`, scope
  `round`. 58 event+round entries are registered in `excluded_events`.
- Before 332,579 = after 332,429 + 150 moved. Every quarantined row is identical to its original.
  No id is in both tables. The other 332,429 rows are byte-identical to the backup. Constructed rounds
  of all 10 events are unchanged.
- Re-running the quarantine moved 0 rows. Re-importing all 150 through `save_matches` (on a copy): 150
  refused and counted, 0 inserted.
- Backup: `mtg_meta.backup-2026-10-02-pre-quarantine.db`. Reversible with
  `python -m scripts.quarantine_matches restore --event <id> --round <n>`.

## 4. Relabel: only `fuzzy_fix` and `alias_drift` applied

Aliases added by this cleanup (user-approved, explicit keys): Azorius Control (Kaheera), Jeskai Control
(Kaheera), Temur Living End, W-U-R-G Domain Zoo, W-U-B-R-G Domain Zoo, Mono Green Amulet Titan. How a
stored label arose is judged against the alias table without these aliases.

Manifest `56b9064a...` (all formats, 320,141 rows after the quarantine).
Changed rows by format and group:

| format | fuzzy_fix | alias_drift |
|---|---:|---:|
| legacy | 5,514 | 5 |
| modern | 10,218 | 0 |
| pauper | 5,613 | 0 |
| pioneer | 2,512 | 0 |
| standard | 8,467 | 157 |
| vintage | 99 | 0 |
| **total** | **32,423** | **162** |

Rows updated: 32,585. (The 99 vintage rows were tagged `vintage` by step 2 before the relabel.)

The previous manifest (`ecc211d7...`) had fuzzy_fix 32,909. The −486 difference is fully explained row
by row: published 'Mono Green Amulet Titan' rows already stored as 'Amulet Titan' are unchanged under
the new alias. No row entered an approved group.

Held, untouched (51,119 rows): fuzzy_guess 9,828; vague 15,277 (colour-only targets such as 'Izzet' and
'Jeskai'); other 10,786; unlabelled 2,886; unmatched 12,342; ambiguous / unrecovered 0.

Checks after apply:
- integrity ok;
- re-plan shows 0 changes in the applied groups;
- row count unchanged (332,429);
- id / event / round / players / result / format / date / source identical on every row;
- changed rows = exactly the approved set, each equal to the manifest's new value;
- 0 held rows touched;
- 0 winner/result inconsistencies (0 before).

Backup: `mtg_meta.backup-2026-10-02-pre-melee-relabel.db`.

## Open

- `other` (10,786) is over-inclusive. It also holds rows affected by aliases added between a row's
  scrape and now: for example 'Mono Green Landfall', 3,700 Standard slots. A per-date alias table from
  git history could separate those rows.
- fuzzy_guess and vague need per-name review; 12,342 unmatched rows have no known cause.
- Six unjoined mtgmelee_437430 rows keep their `standard` tag.

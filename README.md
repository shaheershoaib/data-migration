# data-migration

[![tests](https://github.com/shaheershoaib/data-migration/actions/workflows/test.yml/badge.svg)](https://github.com/shaheershoaib/data-migration/actions/workflows/test.yml)

Prove a data migration actually landed correctly, on the destination, where the
evidence is.

A clean extraction run, matching row counts and a load with no errors are all
compatible with a completely wrong result. This is the discipline for the cases
where they are, plus `migration_check.py`, which makes the mechanical half
executable.

Pure Python standard library: no dependencies, no network, no database driver.
CSV, JSONL or JSON in - the format is the transport, not the database - so it runs
against an extract, in CI, or against a fixture.

```bash
python3 migration_check.py --spec spec.json
```

## The problem

Every failure this skill exists to prevent looked like success at the moment it
happened.

A migration is the work type where **the easiest thing to measure proves the
least**. Row counts reconcile perfectly when a column was never carried. A load
reports zero errors when the destination does not enforce its own enums. A
transform runs clean over half its domain and looks identical to one that covered
all of it. A status backfill keyed on an id that had been re-sequenced attaches
every row to the wrong entity, completely, with no error anywhere.

The defining property: **the correctness of the output cannot be observed from the
input.** So the whole discipline is about proving it on the destination.

## The check that makes the point

Legacy rows routinely assert two things that cannot both be true. A success flag
written when an operation is *submitted* and never cleared when it later fails,
sitting beside the status field that records the real outcome. The row says both
"settled" and "reversed".

Detecting the contradiction is the easy half. The expensive half is **which one
wins**, and that is a business rule, not a technical one: a bounced payment is not
money received.

```json
{"exclusivity": [{
   "name": "a reversal beats a settle-flag - a bounced payment is not money received",
   "key": {"source": "id", "destination": "legacy_id"},
   "destination_column": "status",
   "states": [
     {"name": "reversed", "when": {"payment_state": "REVERSED"}, "destination_value": "REVERSED"},
     {"name": "settled",  "when": {"is_settled": "1"},           "destination_value": "SETTLED"}
   ]}]}
```

```
FAIL  exclusivity-precedence
      case: a reversal beats a settle-flag - a bounced payment is not money received
        rows_checked: 4
        source_contradictions: 2      <- the legacy system's mess, reported
        precedence_violations: 2      <- YOUR transform resolved these the wrong way round
        missing_in_destination: 0
        examples: [{"key": "1", "matched": ["reversed", "settled"],
                    "expected": "REVERSED", "got": "SETTLED"}]
```

Note the two separate counts. Source contradictions are a property of the legacy
data and do not fail the run: you inherited them. Resolving them the wrong way
round is yours, and that fails.

## What it checks

Declare only what applies. Each section of the spec is optional.

| check | catches |
|---|---|
| `exclusivity-precedence` | two mutually exclusive states on one row, and whether the transform let the right one win - and every affected row the destination never received, counted rather than silently skipped (`allow_missing` declares deliberate skips) |
| `key-uniqueness` / `key-uniqueness-destination` | a natural key that maps N:1, a blank/sentinel key that cannot join - and, on the destination side, a double-applied load minting duplicate keys while every value stays right |
| `key-identity` | an id present in both systems that does not mean the same thing, scored against an independent human-readable attribute - the threshold is explicit (`min_match_rate`, default 1.0) and printed, never a silent tolerance |
| `value-reconciliation` | a mapped column whose landed VALUES silently diverged from the source - compared row by row, column by column, over the full population (step 5, executable); blank or duplicated destination keys are excluded and counted, never resolved last-seen-wins |
| `column-coverage` | a field that was never carried, invisible to any row count |
| `coverage-summation` | transformed + skipped + deferred failing to sum to the input - the silent subset that "ran clean" |
| `grain` | a one-to-many flattened to one-to-one, which destroys information while every count still reconciles - and the reverse fan-out, a load applied twice |
| `destination-contract` | types (int, number, ISO date, enum), required-ness, min/max ranges, all-NULL columns, especially where the destination does not enforce them itself |
| `counterexamples` | an inferred field meaning, stated as a hypothesis and refuted by a query (`when` values take a scalar or a list) |
| `provenance` | a hand-supplied mapping artifact older than the data it maps, stale by construction - an entry missing a date, or carrying a non-ISO one, fails rather than silently passing |
| `row-census` | the baseline, which proves the least and is reported first so it is never mistaken for the answer - it blocks only when a declared input has ZERO rows (the wrong-WHERE extract), unless `allow_empty` says that is deliberate |

The spec itself is validated: an unknown section, contract type, or rule key is a spec
error, never a silent skip - a typo'd check is a check that never runs while the run
looks green.

Exit codes: **0** = every declared check passed, **1** = a check failed (a block,
because the transform is not proven), **2** = the spec is invalid.

## The false-block guard

`tests/` seeds a fixture with one instance of every defect class and asserts each
is caught. It also runs a **clean** fixture that must produce zero findings:

```
ok    row-census
ok    key-uniqueness
ok    key-uniqueness-destination
ok    key-identity
ok    value-reconciliation
ok    column-coverage
ok    coverage-summation
ok    grain
ok    destination-contract
ok    counterexamples
ok    provenance

0/11 checks failed
```

That second half matters as much as the first. A checker that cries wolf gets
switched off, and then nothing is checked at all.

```bash
python3 tests/test_migration_check.py
```

## The discipline

`SKILL.md` is the full loop, and most of it is judgment the tool cannot supply:
locate the code that writes and reads each side before you read a schema (a schema is
shape; the code is meaning) and record where each store is and how it is reached in a
brief the project keeps, prove you can reach and write to both systems before designing
anything, census the source's mess, derive the contract from the destination and enumerate what it
actually *enforces*, derive semantics from behaviour rather than names, prove the
join keys before any bulk operation, decide deliberately what happens to values that
cannot be mapped, state coverage as in-scope / transformed / skipped, reconcile by
value over the full population rather than a sample, scope the load so it cannot
destroy what the destination owns, and rehearse at production *size* rather than
production shape.

Two of those exist because a migration across two systems breaks advice that holds
inside one. There is often no shared surrogate key to fall back on when a natural key
turns out non-unique, because ids get re-sequenced at migration; and the transfer path
itself, when source and destination sit on different networks, is routinely the largest
unbudgeted cost in the job.

It is written as a Claude Code skill, so an agent loads it automatically when it
recognises migration work. It reads perfectly well as a checklist for a human.

```bash
git clone https://github.com/shaheershoaib/data-migration ~/.claude/skills/data-migration
```

## Where this sits relative to existing tooling

Published migration tooling, and most ORM tooling, covers **schema mechanics**:
DDL, expand/contract, zero-downtime cutover, rollback, version ordering. It
assumes the data itself is clean. That is a different problem, and the two
compose. Use those for *how* the schema changes; use this for *whether* the data
that landed is right.

The checks here are not novel in data engineering. Assertion frameworks (dbt
tests, Great Expectations, Soda, data-diff) express exactly these destination-side
constraints. Where a project already runs one, prefer **emitting** the contract,
uniqueness and reconciliation checks into it rather than keeping a bespoke
validator: an assertion in the project's own test runner survives after the
migration is over, and a one-off script does not. This tool is for the case where
there is no such framework yet, or the migration is happening before one exists.

The checks matter most *before* the extract exists.
Run them on the source however you can query it; the script is the backstop for what
you pulled, not the first line of defence. Across two systems behind different drivers
there is no single connection that spans both, which is why a live-connection mode
would not help and would cost the property that lets this run anywhere.

## License

Apache License 2.0. Copyright 2026 Shaheer Shoaib. See `LICENSE` and `NOTICE`.

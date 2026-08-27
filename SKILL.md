---
name: data-migration
description: Use when moving or reshaping DATA rather than code - a legacy-system migration, a backfill, a bulk import, an ETL, a re-keying, or a one-off correction script over existing rows. Triggers on "migrate the data", "backfill X", "import from the old system", "reconcile the migration", "why is this row wrong since the migration". NOT for schema-only DDL with no data movement (that is an ordinary schema change, handled by expand/contract), and NOT for code-wide mechanical sweeps like a codemod or rename (that is a mechanical code sweep). The defining property: the correctness of the output cannot be observed from the input, so the whole discipline is about proving it on the destination.
---

# data-migration (the work-type loop for moving data)

A data migration is the work type where **the easiest thing to measure proves the least**.
A clean extraction run, matching row counts and a load with no errors are all compatible
with a completely wrong result. Every failure this skill exists to prevent looked like
success at the moment it happened.

**Boundary:** this is the loop for the TRANSFORM only. It does not replace your normal
review-and-release process - the output still crosses review, CI and deploy like any other
change. What lives here is the discipline that process cannot supply, because no test on
the changed code can tell you the data it produced is wrong.

---

## First - can you REACH both systems, and what does that path cost?

Every step below assumes you can query the source, query the destination, and write to
it. When the two live on different networks that assumption is the largest unbudgeted
cost in the whole job, and it is discovered late, under time pressure, in the middle of
a load.

Establish the path FIRST, and time it:

- **Prove the read and the write end to end before designing the transform** - a trivial
  round trip, one row out and one row back, through the exact channel the real load will
  use. A path that works for a SELECT can fail for a write: execution channels vary in
  whether they allocate a terminal, how large a payload they accept, and how long they
  stay open.
- **Let the channel constrain the design, not the other way round.** Payload caps and
  time limits decide batch size and whether the transform runs where the data is or where
  you are. Discovering the cap mid-load turns a transform into an outage.
- **An extract that crosses a boundary is a point-in-time SNAPSHOT.** Record when it was
  taken. Everything created in the source afterwards is invisible to it, which is the same
  staleness trap as a hand-supplied mapping artifact, arriving by a different route.

If the path is slow or fragile, that is a fact about the migration, not an obstacle to
push past quietly. Budget it.

---

## Step 0 - census the source's MESS before designing the transform

Legacy data is inconsistent in ways its schema does not admit, and every one of those
inconsistencies becomes a silent defect downstream. Before writing any mapping, measure:

- **Key uniqueness.** For every key you intend to join on: `GROUP BY key HAVING COUNT(*) > 1`.
  A natural key that maps N:1 resolves to whichever row it hits first. If it is not unique,
  join on the surrogate id.
- **NULL conventions.** Which columns are nullable, and what does NULL MEAN? A common
  convention is "this FK is NULL, so the identity lives in these other columns" - a
  transform that copies only the FK drops those rows' identity entirely.
- **Value domains.** For each column that will land in a constrained destination field:
  the DISTINCT set actually present. Legacy free-text columns routinely contain values
  outside the enum you are mapping to, plus casing and whitespace variants.
- **Orphans and dangling references.** Rows whose parent no longer exists.
- **Type reality.** A column typed `varchar` that holds numbers will parse - until the one
  row that does not. Money and dates are where this bites.
- **Duplicates and near-duplicates** on the natural identity.

Write the census down. It is the evidence for every scoping decision that follows, and it
is what makes a later "we did not know" false.

## Step 1 - derive the contract from the DESTINATION

Read the destination schema and write the contract it actually requires: types, enum
membership, ranges, required-ness, referential integrity, precision (money in minor units,
timezone handling for dates).

**Then enumerate what the destination actually ENFORCES.** This is the step everyone skips.
Enums stored as free text, foreign keys declared without constraints, permissive numeric or
date parsing, implicit truncation - each means the store will accept wrong data and report
success. **The weaker the enforcement, the more the burden of proof sits on your own
validation**, and the less a clean load tells you.

## Step 2 - derive SEMANTICS from behaviour, not names

A field's meaning comes from what the producing system DOES with it, never from what it is
called. A boolean named for success may be set on submission and never cleared on failure.
A timestamp may never be populated. Where two columns disagree, find which one the legacy
system itself treats as authoritative - usually the one its own UI and reports read.

For any field whose meaning you inferred rather than observed, that inference is a
HYPOTHESIS - and a hypothesis is testable, so **write the COUNTEREXAMPLE QUERY**: find the
rows where the name predicts one thing and the authoritative field says another. Zero rows
supports the inference; any rows refute it, and the count tells you the blast radius.

This is the single cheapest check in the whole loop. "Is this flag really what it says?"
becomes `WHERE looks_successful = 1 AND authoritative_status IN (<failure states>)` - one
query, an exact number, no opinion. A flag whose name promised success but was set on
submission and never cleared on failure returns tens of thousands of rows here, in seconds,
before a single row is migrated.

## Step 2b - resolve MUTUALLY EXCLUSIVE states, and declare which one wins

Legacy rows routinely assert two things that cannot both be true: a success flag written
when an operation is SUBMITTED, never cleared when it later fails, sitting beside the status
field that records the real outcome. The row says both "succeeded" and "failed".

**Detecting the contradiction is the easy half. The expensive half is which one WINS.** A
transform that reads the flag rather than the authoritative status migrates failures as
successes, and the result looks complete - full row counts, no errors, money in the wrong
state. Precedence is a business rule, not a technical one: a bounced payment is not money
received, a cancelled order is not fulfilled, a superseded record is not current.

So:
1. **Find the contradictions before mapping** - `WHERE flag = 'success' AND status IN
   (<failure states>)`. The count is the blast radius and it decides how much this matters.
2. **Declare the precedence explicitly**, highest first, and say WHY in business terms. If
   you cannot state why one wins, that is a question for whoever owns the data, not a
   default to pick quietly.
3. **Verify the destination honoured it for every affected row** - not a sample. This is the
   `exclusivity` check in `migration_check.py`: source contradictions are REPORTED (the mess
   belongs to the legacy system) while precedence violations FAIL (resolving it the wrong way
   round is yours).
4. **Never let the losing flag survive into a downstream filter.** The original damage is
   usually compounded by a query that later selects on the flag rather than the resolved
   status - fix the value, then find every reader of it. Correcting the data and leaving a
   downstream query still filtering on the losing flag reproduces the same defect.

## Step 3 - prove the join keys BEFORE any bulk operation

An id present in both systems is not evidence it means the same thing. Ids get
re-sequenced at migration, reused, or scoped per-tenant.

Validate each key against an **independent human-readable attribute** - a name, a document
number, a natural key - and state the match rate. A wrong key does not fail loudly: it
produces a complete-looking result in which every row is attached to the wrong entity, and
that is indistinguishable from success without this check.

**Across two systems there is often no shared surrogate at all.** "If the natural key is
not unique, join on the surrogate id" is within-database advice: ids get re-sequenced at
migration, so the destination's id and the source's id are unrelated even where both
exist. That leaves the case with no clean answer - a natural key that maps N:1, and no
surrogate to fall back to.

Do not resolve it by picking a match. Instead:

1. **Partition the rows by whether the key is ambiguous**, and count both sides. Ambiguity
   is usually concentrated, not spread: placeholder and filler values (repeated digits,
   empty-equivalents, a default the legacy UI wrote when the field was skipped) generate
   most of the collisions, and they are recognisable.
2. **Land the unambiguous rows now.** They are the majority and they are provable.
3. **Re-key the ambiguous ones through a higher-grain parent** that IS unambiguous - the
   owning entity one level up - and treat them as a separate phase with its own evidence.
   A parent-scoped match is a weaker claim than a direct key match, so it earns its own
   verification rather than riding along with the clean rows.
4. **Report the deferred count as part of coverage.** A phase you named is a decision; a
   phase you silently dropped is the "it ran clean over a subset" failure wearing a
   different hat.

## Step 3b - decide the FALLBACK for values that cannot be mapped

The census finds values with nowhere to land: outside the destination's enum, malformed,
or absent. Finding them is not the decision. What happens to those rows is, and left
unstated it gets made row-by-row by whatever the code does when a lookup misses - usually
NULL, or a default nobody chose.

- **Count the affected rows before choosing.** A fallback applied to nine rows and one
  applied to nine thousand are different decisions, and the count is what tells you which
  one you are making.
- **Prefer DERIVING the value from an authoritative related record over a constant.** A
  child row missing a dimensional value can often inherit it from its parent, which is
  both more likely correct and re-derivable later. A hardcoded default is unfalsifiable
  after the fact: nothing distinguishes a row that genuinely held that value from a row
  that fell back to it.
- **Mark fallen-back rows so they stay identifiable**, or record their keys. Otherwise the
  decision dissolves into the data and cannot be revisited when someone asks how many rows
  were guessed.
- **Never let unmappable mean silently skipped.** Every row is transformed, deliberately
  fallen back, or skipped with a counted reason. Those three must sum to the input.

## Step 4 - transform, and state COVERAGE

Report rows **in scope / transformed / skipped**, with the reason for each skip. "It ran
clean" over a subset is not completeness - a transform that silently covers half its domain
looks identical to one that covers all of it.

**Census COLUMNS, not just rows.** A row census cannot see a field that was never carried:
every row moves, one column is silently absent, and the count is perfect. Enumerate the
source's columns against the destination's and account for each as **mapped / deliberately
dropped / defaulted**. A dropped column is a decision; an unlisted one is an accident.

**Assert the GRAIN survived.** A transform that collapses a one-to-many into a one-to-one -
per-contact rows flattened to per-customer, per-line detail summed to a header - destroys
information while every row count still reconciles. State the grain on both sides and check
the cardinality: if the source had N children per parent and the destination has one, say
whether that was intended and what was lost.

Anything hand-supplied (a spreadsheet, an extract, a mapping file) carries **provenance**:
name the artifact and its date, **and compare that date against the data it maps**. An
artifact older than the extract it is being applied to is stale by construction - it cannot
know about anything created since. Staleness is invisible in the output, so it has to be
caught on the input.

## Step 5 - reconcile BY VALUE over the FULL population

Not a sample, and not row counts. Compare the destination's values against the source of
truth for every row and report the **count of mismatches**; require zero, or explain each
class that remains.

This is also how a denormalized or summary field is caught drifting from the records it
summarises: derive the value from the authoritative rows, compare against the stored one
across the whole population, and emit a backfill for the difference.

## Step 6 - scope the load, and protect what the destination OWNS

A destination accumulates rows the source never had: users, roles, permissions, settings,
anything created after cut-over. **A reload scoped to "all tables" destroys them.** Scope
every load to the tables the transform owns, and name the excluded tables explicitly.

Destructive operations get a restore path proven BEFORE they run, not discovered after.

## Step 6b - rehearse at PRODUCTION SCALE, and make the run resumable

Borrowed from the established schema-migration practice, because a data transform fails at
scale in ways it never fails on a sample - and the failure mode is usually worse than the
bug:

- **Rehearse on production-SIZED data, not production-shaped data.** A transform verified on
  a thousand rows tells you the logic is right and nothing about whether it completes. Time
  it at full volume before it matters.
- **Batch by an INDEXED key; never one giant transaction.** A single bulk statement over
  millions of rows holds locks for its whole duration, and its ROLLBACK is slower than the
  statement was - a failed run can hold locks for hours and block every other writer, which
  is a bigger outage than the defect you were fixing. Batch, commit, and make each batch
  independently re-runnable.
- **Check the join keys are indexed** before running anything that joins at volume. An
  unindexed join on a large table is the difference between minutes and hours.
- **Run long operations DETACHED and poll.** Remote-execution channels have their own
  timeouts; an operation that outlives its channel gets killed mid-write, which is the worst
  possible moment.
- **Checkpoint, so a killed run resumes instead of restarting.** Record what has been
  processed; a transform that must start over from zero after a failure will be run under
  pressure, and that is when it gets run wrong.
- **Watch for column constraints that abort the BATCH, not the row.** An unsigned column
  meeting a negative value, or a value exceeding a width, can fail the entire statement -
  clamp or validate before the write, and know which failures are per-row and which are
  fatal to the batch.

**Keep schema (DDL) and data (DML) as separate migrations.** They have different risk,
different rollback, and different rehearsal needs; bundling them means a data defect forces
a schema rollback. And once a migration has been APPLIED anywhere, treat it as immutable -
correct it with a new one rather than editing history that other environments already ran.

## Step 7 - close out

The receipt is the destination-side evidence, not the run log:
- the contract asserted, and what the destination does/does not enforce
- key uniqueness + match-rate against an independent attribute, and the count of rows
  deferred as ambiguous rather than matched by guess
- the coverage census (in scope / transformed / skipped + reasons), and the count of rows
  that took a fallback rather than a mapped value
- the full-population value reconciliation (mismatch count)
- spot checks BY VALUE on representative LEGACY and edge rows, not only freshly-created ones

A migration that cannot show these has not been verified - it has been run. Take the
honest downgrade rather than calling it done.

## Running the mechanical checks

Most of this loop is judgment. Seven of the checks are not - they are queries whose answer
is a number, and they are executable. They live in `migration_check.py`, beside this file:

```bash
python3 migration_check.py --spec spec.json
```

Declare only what applies; each section is optional. It checks **mutually-exclusive state precedence** (did the transform let the right flag win), **key uniqueness** (a natural
key mapping N:1), **key identity** (match rate against an independent attribute), **column
coverage** (every source column mapped / dropped / defaulted), **grain** (children-per-parent
on both sides), the **destination contract** (types, enums, required, all-NULL), your
**counterexample queries** (an inferred meaning is a hypothesis), and **provenance** (an
artifact older than the data it maps is stale by construction).

It exits **non-zero on any failure** - a failing check is a block, because the transform is
not proven. CSV in, so it runs against an extract, in CI, or against a fixture with no
database driver.

`tests/` seeds a fixture with one instance of every defect class above and asserts each is
caught - plus a CLEAN fixture that must produce ZERO findings. That second half matters as
much as the first: a checker that cries wolf gets switched off, and then nothing is checked.

**These are the floor, not the ceiling.** They prove the mechanical properties; semantics,
grain intent and coverage decisions still need the steps above. And prefer emitting the same
assertions into whatever data-quality framework the project already runs (see below) so they
outlive the migration.

## Where this sits relative to existing tooling

Published migration tooling, and most ORM tooling, covers **schema mechanics** - DDL,
expand/contract, zero-downtime cutover, rollback, version ordering - and assumes the data
itself is clean. That is a different problem from this one, and they compose: use them for
HOW the schema changes, use this for WHETHER the data that landed is right.

The checks here are not novel in data engineering - assertion frameworks (dbt tests, Great
Expectations, Soda, data-diff) express exactly these destination-side constraints. Prefer
EMITTING the contract, uniqueness and reconciliation checks into whichever of those a
project already runs, rather than writing a bespoke validator: an assertion in the project's
own test runner survives after the migration is over, and a one-off script does not.

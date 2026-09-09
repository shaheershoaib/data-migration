---
name: data-migration
description: 'Use when moving or reshaping DATA rather than code - a legacy-system migration, a backfill, a bulk import, an ETL, a re-keying, or a one-off correction script over existing rows. Triggers on "migrate the data", "backfill X", "import from the old system", "reconcile the migration", "why is this row wrong since the migration". NOT for schema-only DDL with no data movement (that is an ordinary schema change, handled by expand/contract), and NOT for code-wide mechanical sweeps like a codemod or rename (that is a mechanical code sweep). Applies to any store - relational, document, key-value, warehouse - and to moves between kinds. The defining property: the correctness of the output cannot be observed from the input, so the whole discipline is about proving it on the destination. Also when only a schema dump or an extract has been handed over and the application code for either side has not.'
---

# data-migration (the loop for moving data)

In a migration the easiest thing to measure proves the least. A clean run, matching row
counts and a load with no errors are all compatible with a completely wrong result, and
every failure this file exists to prevent looked like success at the moment it happened.
This is the loop for the TRANSFORM only; review, CI and deploy still apply to its output.

**Two ways in, one loop.** Either you are about to BUILD the migration (the transform at
step 4 is yours; steps 5 to 7 prove it) or a migration has ALREADY RUN and you are asked
whether it is right (the transform is someone else's claim; steps 0 to 3 say what it should
have done; 5 to 7 are the verdict). Nothing changes between the two but who wrote step 4.

## Start here

1. **Census the handover with the tool before forming any opinion.** If the folder holds a
   `findings.md`, your harness ran it: read it end to end and carry every number below. If
   not, run `python3 migration_census.py --discover <folder> --out findings.md` (no
   declarations; it infers sources, keys, links, cross-source overlaps and same-entity pairs,
   and writes the findings as sentences with counts, largest first). The numbers you would
   not have thought of are the point.
2. **Write the brief** (template under Intake): every line filled or turned into a question
   to a named person. For any side whose code you do not have, the request for that code is
   the first question.
3. **Then run the loop in order** and end with the receipt lines in step 7. Every rule
   below has its reasoning and its worked cases in `references/loop-in-full.md`; read that
   when a rule seems wrong for your case, not before starting.

## Sizing the loop

The loop has one shape; a small job changes how DEEP each step goes, never which steps
run. Size by four questions: how many rows; does a wrong row cost money, identity or trust;
is the destination live; can the load be undone. Small and low-stakes: one reach round
trip, census only the mapped columns, semantics only where a name is not literally the
meaning, skip 6b with the row count that justifies it. Never shortened at any size: the
key proof, the coverage arithmetic, the by-value reconcile and the receipt - at small volume
they are the cheapest steps in the loop. A skipped step is written down with its reason.

## Intake - the code and the paths, before the schema

A schema is the SHAPE of the data; its MEANING lives in the code that writes each store
and the code that reads it back for people. A question to the team of the form "what does
column X mean" or "what fires on insert" is a request for someone to read code you could
read: ask for the CODE, answer it yourself, and take only the business call to the team.

**Discover first, then ask ONCE.** Look in the working tree, the project's instruction
files, the environment and deploy configuration, any connected database tool. Ask only
for what is missing, as one batch, by ROLE and never by technology:

- Source: where is the code that WRITES its store (the application and every other writer:
  jobs, procedures, imports, scripts); where is the code that READS it for people (screens,
  reports, exports - these decide the authoritative field); how is the store reached, from
  where, with what limits; where do the credentials LIVE (a pointer, never values); is it
  frozen or still taking writes; who owns the data and rules on precedence.
- Destination: where is the code that WRITES it (models, validation, defaults, hooks) and
  the code that will READ the migrated rows; how is it reached, and is that path usable for
  writes at volume; where do credentials live; is it LIVE during the migration; is there a
  rehearsal environment at production size.

"Unknown" and "unavailable" are valid answers; each becomes a receipt line.

**The evidence ladder bounds what you may declare.** Rung 1: the code was read; semantics
and precedence are DERIVED, then tested with counterexample queries. Rung 2: the running
system was observed (screens, reports, vendor docs); each meaning is a hypothesis carrying
its observation. Rung 3: schema and census only; a name is not evidence, so at rung 3 you
do NOT declare field meaning or precedence, however hedged - block the decision, name the
code or person that unblocks it, and carry on with what the rung supports (types, keys,
coverage, reach). A mapping declared at rung 3 "with medium confidence" is the face-value
mapping this file exists to prevent. Rung 1 is the normal case; ask before settling.

**The brief is OUTPUT.** Whatever you deliver carries it as a section:

```markdown
# Migration brief: <source> -> <destination>   (as of <date>)
## Source
- store: <kind, host or service>; frozen: <yes/no>; access: <ro/rw>; reached via: <path, limits>
- credentials live at: <pointer>; code that writes it: <path>; other writers: <...>
- code that reads it for people: <...>; evidence rung: <1/2/3>; data owner: <who>
## Destination
- store: <...>; live during migration: <yes/no>; reached via: <...>; write path proven: <date>
- credentials live at: <pointer>; code that writes it: <...>; code that reads migrated rows: <...>
- fires on write: <hooks, triggers, recomputes>; rehearsal environment: <...>; evidence rung: <...>
## Open
- <question> -> <who> -> <blocks which decision>
```

## Reach

Prove read, move and write end to end before designing anything, through the exact
channels the real load will use, and time them: reading, moving and writing are routinely
three mechanisms with three limits, and the write path is the one exercised last. Let the
channel constrain the design (payload caps and time limits decide batch size and where the
transform runs). An extract that crosses a boundary is a point-in-time snapshot: record
when. The application's own configuration is the map to its store - host, database, the
charset the client declares, where credentials come from - read it there before asking.

## Step 0 - census the mess, then decide what it means

The tool prints the numbers (presence split into absent / null / empty and crossed with
every category; spellings that fold together; ids that are not digits; values with more
than two decimals; magnitude outliers; dates in the future; dangling links; key uniqueness
raw and folded; flag-by-category crosstabs; overlaps and same-entity pairs across sources,
with only-in-each and the rows that deviate from the majority vocabulary mapping). What it
cannot do is decide, and these decisions are yours before any mapping:

- **Soft deletes**, per table: find every "not really here" marker the source uses and say
  whether it migrates. Usually migrate the row, carry the marker, confirm the destination's
  filters honour it - which starts with checking the destination HAS the column.
- **Sentinels** are missing, not data: a placeholder name, a zero meaning "not calculated".
- **Orphans**: decide their disposition now, not at load time.
- **Two sources describing the same entity** (a mirror and its record, an export and its
  API): run `migration_check.py` between them, one as source and one as destination, with
  `key` and `reconcile`, so only-in-one, only-in-the-other and differing values are counts
  before any decision about which one wins.
- **Schemaless sides**: absence is not null; a field's type varies between documents;
  embedded arrays are the grain (assert their length); denormalized copies must all be
  updated; array order usually means something.

Write the census down. It is the evidence for every decision that follows.

## Step 1 - the contract comes from the DESTINATION

Read the destination and write what it requires: types, enum membership, ranges,
required-ness, referential integrity, precision (money in minor units). Pin the timezone of
every datetime column on both sides; convert per row with a zone-aware library, never an
offset constant, and recompute every datetime over the full population - spot rows on a DST
boundary prove the method, not the data. Then enumerate what the destination actually
ENFORCES: free-text enums, unenforced foreign keys, permissive parsing, implicit truncation
all accept wrong data and report success, and the weaker the enforcement the more the proof
sits on you. The contract includes what the APPLICATION enforces on its own writes - read
its models, validators and defaults, because a direct load bypasses them - and if migrated
rows are meant to be distinguishable by a marker, CHECK the marker on the landed data.

## Step 2 - semantics from behaviour, never from names

A field means what the producing system DOES with it. For each column you map, find in the
code: its WRITERS (every assignment; two writers that disagree are step 2b before a row is
queried), its READERS (the one the business reconciles against is authoritative; a column
nobody reads is a candidate for dropping), its CONSTANTS (enum vocabularies, prefix and
composite-key conventions), its VALIDATION (what the application refuses to write). A text
search is enough. Every inferred meaning is a HYPOTHESIS: write the counterexample query -
rows where the name predicts one thing and the authoritative field says another - and the
count is the blast radius. Where there is no code (rung 2 or 3), say so at the decision and
do not fill the gap with the name.

## Step 2b - mutually exclusive states: declare which wins

A success flag set on submission and never cleared sits beside the status that records the
outcome; the row asserts two states. Count the contradictions first; declare the precedence
highest first and say WHY in business terms (if you cannot, it is a question for the data
owner, not a default); verify the destination honoured it for every affected row; and find
every downstream reader of the losing flag, or the defect reappears through a filter.

## Step 3 - prove the join keys before any bulk operation

An id present in both systems is not evidence it means the same thing: ids get
re-sequenced, reused, scoped per tenant (then the key is the PAIR, in every join, every
reconcile, every delete). Validate each key against an independent human-readable
attribute and report the match rate, raw and folded, both ways; the gap is rows whose match
depends on a rule the two systems do not share. A sentinel in the key column ("NULL", "0")
force-maps everything to one row: filter at the source and dedup maps to the single real
value. When a natural key maps N:1 and there is no shared surrogate, do not pick a match:
partition the ambiguous rows, land the rest, find the ambiguous ones a DIFFERENT key path
with its own uniqueness and match-rate proof, and report the deferred count in coverage.

## Step 3b - the fallback for values that cannot be mapped

Count the affected rows before choosing. Prefer deriving from an authoritative related
record over a constant, but only where the parent's value was true when the child was
written - inheriting today's address onto a 2019 document rewrites history. Mark
fallen-back rows so they stay identifiable. Transformed + fallen back + skipped must sum
to the input; unmappable is never silently skipped.

## Step 4 - transform, and state coverage

Rows in scope / transformed / skipped with reasons. Columns mapped / deliberately dropped /
defaulted - a row census cannot see a column that was never carried. Grain on both sides,
with the cardinality checked. Every hand-supplied artifact carries a date compared against
the data it maps; older is stale by construction.

## Step 4b - many sources, one destination: the merge

Run the loop once per source first; the same column name means different things in two
systems more often than not. Then: census the OVERLAP on an independent attribute before
designing the match; declare the MATCH RULE with its rung (never a name alone; at rung 3 it
is blocked); declare SURVIVORSHIP per field with its rung - step 2b between systems, justified
from whose code maintains the field - and keep losing values in a conflict list; keep a MERGE
LEDGER (source, source key, destination key, landed / merged / skipped / deferred) so that
source rows = destination rows + merged + skipped + deferred, with per-source provenance on
every destination row; hunt FALSE MERGES (members of one group disagreeing on an attribute
the rule did not use) and FALSE SPLITS (landed rows sharing one) over the full population;
state the SNAPSHOT SKEW between N extracts taken at N times. Then steps 5 to 7 run on the
merged destination. The checker's `merge` section makes the ledger arithmetic and the two
candidate counts mechanical.

## Step 5 - reconcile BY VALUE over the FULL population

Not a sample, not counts. Fix the comparison rule first: money as integers in minor units,
never float equality; state every normalization you apply, because each is a difference you
decided not to see; compare RAW before folded and report the gap as rows to inspect (a
re-cased legal name or a changed Unicode form renders identically and fails every exact
lookup); report the summed signed difference as well as the count. A UNIFORM mismatch class
(same sign, factor or offset) is a systematic defect. "Explain each class" means naming the
transform line that produces it and why it is correct - and a class the transform
PRE-EXPLAINS in a comment is still a class to verify against the code that reads the value:
if the reason cites a rule, system or import that neither codebase nor the handover
contains, the class is OPEN. Denormalized and summary fields are recomputed with the
destination's own formula, verbatim, over every row; a filter or floor the formula does not
have reproduces the defect.

## Step 6 - scope the load; protect what the destination owns

Name the tables the transform owns and the ones it never touches (a reload of "all tables"
destroys users, roles and everything created since cut-over). Exclude rows another process
depends on in their CURRENT state. Read what the destination DOES on write - hooks and
signals in the application, triggers and FK actions in the store; a direct load bypasses
the first layer and still fires the second - and disable deliberately, on the record. Reset
id sequences after explicit inserts. Prove a restore SCOPED to the owned tables before the
load; if the destination is live, roll-forward is the only direction, said before batch one.

## Step 6b - production scale, and a run that resumes

Rehearse at production SIZE. Batch by an indexed key, never one transaction; run detached
and poll. Make the load idempotent on a key observable in the destination alone, checked at
the grain of the whole unit of work and written in one transaction - otherwise persist which
source rows were applied as a table in the destination. Know which constraint failures abort
the batch. Declare the charset at every hop; round-trip one non-ASCII row byte for byte to
prove the channel, then compare every non-ASCII value byte for byte after the load. Name the
columns in every load statement. Plan the DELTA before the load: freeze the source or name a
delta pass, and reconcile after cut-over. When the extract does not fit the channel, move
DIGESTS (per-row, over the normalized mapped columns, built identically on both sides) and
pull full rows only for differing keys; run the census where the data is and move results. If
the source keeps writing, the loop runs per sync against a common WATERMARK; a source with no
change marker has no delta, only a full re-compare. Keep schema (DDL) and data (DML) as
separate migrations; an applied migration is immutable.

## Step 6c - a defect in one row is a class

Write the predicate that selects it, run it over the whole table, fix every match, and
close on the class being EMPTY, never on the reported row being right.

## Step 7 - the receipt

Destination-side evidence, not a run log: the contract and what the destination enforces;
key uniqueness and identity match rate with the deferred count; coverage in scope =
transformed + skipped + deferred, with columns mapped / dropped / defaulted and the
fallback count; the full-population reconciliation with mismatches per class explained;
by-value spot checks on legacy and edge rows; the evidence rung each side was on and which
decisions were BLOCKED because of it; the brief, updated. The lines a reviewer reads first:

```
RECEIPT    <source> -> <destination>   run <date>   build <sha>
reach      source via <path>; destination via <path>; write round trip <ok/failed, date>
evidence   source rung <n>, destination rung <n>; blocked decisions: <n> (<which>)
keys       <key>: source unique <yes/no>; identity <rate> vs <attribute>; deferred <n>
coverage   in scope <n> = transformed <n> + skipped <n> + deferred <n>; columns <a/b/c>
reconcile  <n> rows compared, <m> mismatches in <k> classes; each: <line + why, or OPEN>
merge      (consolidations) <sum> = landed + merged + skipped + deferred; conflicts <n>; splits <n>
```

A migration that cannot show these has not been verified; it has been run. Take the honest
downgrade rather than calling it done.

## The mechanical checks

Two stdlib scripts sit beside this file. `migration_census.py` is step 0 as numbers and
never blocks. `migration_check.py --spec spec.json` reads CSV, JSONL or JSON extracts (never
a live connection, so it runs anywhere) and checks: key uniqueness on both sides; identity
match rate against an independent attribute (threshold 1.0 by default); value
reconciliation over the full population; column coverage; coverage summation; grain in both
directions; the destination contract (types, enums, required, ranges, all-NULL); your
counterexample queries; provenance dates; mutually-exclusive precedence, with affected rows
the destination never received counted as failures; the evidence rung of every declared
decision (rung 1 or 2 names its source, rung 3 is blocked with an unblocker, a precedence
applied through `exclusivity` must rest on rung 1 or 2, and `exclusivity` with no `evidence`
section fails); and, for consolidations, the merge ledger. An unknown section or key is a
spec error (exit 2), never a silent skip. Every undeclared section prints as NOT RUN with
the cost of its absence, because a thin spec looks identical to a thorough one. Exit 0 =
every declared check passed; 1 = a check failed, which is a block; 2 = invalid spec.

Every check that can block has a declared way past it, and declaring one is a recorded
claim: `key.allow_missing` / `allow_unmatched` (a scoped or phased load), `key.identity.min_match_rate`
(almost never), `counterexamples[].allow_no_match`, `contract[col].sentinels: false` ("NA" is
Namibia), `coverage.skipped` / `deferred` (always with the reason), `allow_empty` (almost
never), `evidence.decisions[].blocked: true` (rung 3 on that side), `merge.allow_same_source_merges`,
`merge.max_conflicting_merges`, `merge.max_split_candidates`, `merge.allow_destination_only`.
A number that makes a check unfalsifiable is the same as deleting it, and the output prints
the value so a reviewer can see which you did. Presence of a decision is enforceable; its
correctness is not.

Run the checks BEFORE you trust an extract, in the source's own dialect if you can; the
script is the backstop. Prefer emitting the same assertions into whatever data-quality
framework the project already runs, so they outlive the migration.

## What this loop cannot see

It names the defect classes that have already reached production somewhere and looked like
success. A class it does not name surfaces only as an unexplained mismatch class in step 5
or a report in step 6c, found by a person reading the numbers; when that happens the fix is
a line in this file, not a bigger sample. Schema-migration tooling (DDL, expand/contract,
cutover, rollback) is a different problem and composes with this one: use it for HOW the
schema changes, use this for WHETHER the data that landed is right.

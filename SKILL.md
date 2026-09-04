---
name: data-migration
description: Use when moving or reshaping DATA rather than code - a legacy-system migration, a backfill, a bulk import, an ETL, a re-keying, or a one-off correction script over existing rows. Triggers on "migrate the data", "backfill X", "import from the old system", "reconcile the migration", "why is this row wrong since the migration". NOT for schema-only DDL with no data movement (that is an ordinary schema change, handled by expand/contract), and NOT for code-wide mechanical sweeps like a codemod or rename (that is a mechanical code sweep). Applies to any store - relational, document, key-value, warehouse - and to moves between kinds. The defining property: the correctness of the output cannot be observed from the input, so the whole discipline is about proving it on the destination. Also when only a schema dump or an extract has been handed over and the application code for either side has not.
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

## The loop at a glance

The `mechanical` column names the spec section in `migration_check.py` that makes the
check executable; everything else is judgment the steps below carry.

| step | the question it answers | mechanical |
|---|---|---|
| Intake | where is the code that WRITES and READS each side, and how is each store reached? | - |
| Reach | can you read, move and write end to end - and what does the path cost? | - |
| 0 census | what mess does the source actually contain? | `key` (uniqueness), `contract` on an extract |
| 1 contract | what does the destination require - and what does it actually ENFORCE? | `contract` |
| 2 semantics | does each field mean what its name says? | `counterexamples` |
| 2b exclusivity | when a row asserts two states, which one wins? | `exclusivity` |
| 3 keys | do the join keys mean the same thing in both systems? | `key` + `identity` |
| 3b fallbacks | what happens to values that cannot be mapped? | - |
| 4 coverage | is every row, column and grain accounted for? | `columns`, `grain`, `coverage` |
| 5 reconcile | do the landed values match the source, over the FULL population? | `reconcile` |
| 6 scope | can the load touch only what it owns - and what does the destination DO on write? | - |
| 6b scale | does it complete at production size, and can it resume? | - |
| 6c classes | is the defect's whole CLASS empty, not just the reported row? | - |
| 7 close-out | can you show destination-side evidence, not a run log? | - |

---

## Intake - locate the CODE and the PATHS before you read a schema

A schema is the SHAPE of the data. Its MEANING lives in the code that writes each store
and the code that reads it back for people, and every semantic step below (1, 2, 2b, 3,
6) is an instruction to read that behaviour. This step is where you get it. Skipping it
does not make the mapping faster; it moves the reading onto whoever answers your
questions, one fact at a time, and they answer slower and less completely than a text
search would.

The tell: a question to the team of the form "what does column X mean", "which field does
the old screen read", "what fires when a row is inserted" is a request for someone else to
read code you could read. Ask for the CODE, answer the question yourself, and take to the
team only the part that is a business call.

**Discover first, then ask ONCE.** Before asking anyone, look: is either application
checked out in or near the working tree; what do the project's own instruction files and
docs say; what do the environment files and deploy configuration point at; is a database
tool already connected. Ask only about what is still missing, and ask it as one batch at
the start rather than as each later step trips over the gap.

**The questions, by ROLE, never by technology.** The answers will name the technology;
the questions must not assume one.

For the SOURCE (the system being migrated from):
- Where is the code that WRITES its store: the application, and every other writer
  (scheduled jobs, stored procedures, imports, one-off scripts)?
- Where is the code that READS it for people: screens, reports, exports? These define
  what the business treats as true, and they decide step 2's authoritative field.
- How is the store reached (direct, bastion, VM, container, vendor export only), from
  where, and what limits does that path have?
- Where do the credentials LIVE - a pointer, such as the application's configuration on
  its host - never the values themselves.
- Is it frozen for the migration or still taking writes? Is your access read-only?
- Who owns the data and can rule on a precedence question?

For the DESTINATION:
- Where is the code that WRITES its store: models, validation, defaults, hooks? Where is
  the code that will READ the migrated rows: the screens and filters that render them?
- How is it reached, and is that same path usable for writes at volume?
- Where do the credentials live?
- Is it LIVE, taking application writes, during the migration?
- Is there a rehearsal environment at production size?

"Unknown" and "unavailable" are valid answers. Each becomes a line in the receipt rather
than a gap discovered later.

**The evidence LADDER, and what each rung lets you declare.** Record which rung each side
is on:

1. **Code readable** (writers and readers). Semantics and precedence are DERIVED, stated,
   and then tested with the counterexample queries of step 2.
2. **Running system observable** (screens, reports, exports, vendor documentation) but no
   code. Semantics are OBSERVED per field; each is a hypothesis carrying the observation
   that produced it.
3. **Schema and census only.** Semantics cannot be derived, so every meaning is a guess by
   name, and this skill's rule is that a name is not evidence. At this rung do NOT declare
   field meaning or precedence, however hedged: block that decision, name the code or the
   person that unblocks it, and carry on with what the rung does support (types, key
   uniqueness, coverage, reach). A mapping declared here at "medium confidence" is the
   face-value mapping this skill exists to prevent, wearing a confidence label.

Rung 1 is the normal case, not a luxury: the legacy application usually exists somewhere
even when nobody thought to hand it over. Ask before settling for rung 3.

**Write the answers into a MIGRATION BRIEF the project owns.** A migration outlives a
session; re-asking drifts and re-deriving costs. Keep the brief where the project keeps
its other durable facts (its agent instruction file, a docs directory), reference it from
there, and READ IT FIRST on every later run so you ask only for what it lacks. The shape:

```markdown
# Migration brief: <source> -> <destination>   (as of <date>)

## Source
- store: <kind, host or service, database>; frozen: <yes/no/since>; access: <read-only/rw>
- reached via: <path, from where, limits observed>
- credentials live at: <pointer>
- code that writes it: <path or repo>; other writers: <jobs, procedures, scripts, or "none found">
- code that reads it for people: <screens, reports, exports>
- evidence rung: <1 code / 2 running system / 3 schema only>
- data owner: <who rules on precedence>

## Destination
- store: <...>; live during migration: <yes/no>
- reached via: <...>; write path proven: <date, batch size, time>
- credentials live at: <pointer>
- code that writes it: <models, validation, hooks>; code that reads the migrated rows: <...>
- fires on write: <hooks, triggers, notifications, recomputes; or "none found">
- rehearsal environment: <where, size relative to production>
- evidence rung: <...>

## Open
- <question> -> <who> -> <blocks which decision>
```

---

## Reach - can you reach both systems, and what does that path cost?

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
- **Expect the "channel" to be several channels.** Reading the source, moving the data,
  and writing the destination are routinely three different mechanisms with three different
  limits, and proving one says nothing about the others. Prove each end to end. The write
  path is the one that surprises people, because it is the one exercised last.
- **Let the channel constrain the design, not the other way round.** Payload caps and
  time limits decide batch size and whether the transform runs where the data is or where
  you are. Discovering the cap mid-load turns a transform into an outage.
- **An extract that crosses a boundary is a point-in-time SNAPSHOT.** Record when it was
  taken. Everything created in the source afterwards is invisible to it, which is the same
  staleness trap as a hand-supplied mapping artifact, arriving by a different route.
- **The application's own configuration is the map to its store.** Host, port, database
  name, the charset the client declares, and where the credentials come from all sit in the
  code intake located; read them there before asking anyone, and carry the declared charset
  into step 6b.

If the path is slow or fragile, that is a fact about the migration, not an obstacle to
push past quietly. Budget it.

---

## Step 0 - census the source's MESS before designing the transform

Legacy data is inconsistent in ways its schema does not admit, and every one of those
inconsistencies becomes a silent defect downstream. Before writing any mapping, measure:

- **Key uniqueness.** For every key you intend to join on: `GROUP BY key HAVING COUNT(*) > 1`.
  A natural key that maps N:1 resolves to whichever row it hits first. If it is not unique,
  do NOT fall back to the surrogate id: across two systems the ids are unrelated
  (step 3). Record the collision count and the values causing it; step 3 decides what
  happens to them.
- **NULL conventions.** Which columns are nullable, and what does NULL MEAN? A common
  convention is "this FK is NULL, so the identity lives in these other columns" - a
  transform that copies only the FK drops those rows' identity entirely.
- **Value domains.** For each column that will land in a constrained destination field:
  the DISTINCT set actually present. Legacy free-text columns routinely contain values
  outside the enum you are mapping to, plus casing and whitespace variants.
- **Orphans and dangling references.** Rows whose parent no longer exists - and DECIDE their
  disposition here, not at load time. Under an enforced FK they abort the batch; under an
  unenforced one they land dangling and the application renders a blank where a parent belongs.
- **Soft deletes.** Find every "not really here" marker the source uses - `deleted_at`,
  `is_deleted`, a status code, an archive table, a row the legacy UI filters out - and state
  per table whether it migrates. Both defaults are wrong on their own: migrating them
  resurrects records the business deleted, and dropping them orphans the live rows that still
  reference them. The usual answer is to migrate the row, carry the marker, and confirm the
  destination's own filters honour it - which starts with checking the destination HAS that
  column at all.
- **Type reality.** A column typed `varchar` that holds numbers will parse - until the one
  row that does not. Money and dates are where this bites.
- **Encoding reality.** Mojibake and double-encoded UTF-8 (`Ã©` where `é` belongs) survive
  every row count and most contracts. Census the non-ASCII values in name-like columns
  before the extract locks them in.
- **Duplicates and near-duplicates** on the natural identity.

Write the census down. It is the evidence for every scoping decision that follows, and it
is what makes a later "we did not know" false.

## Step 0b - if either side is SCHEMALESS, census the SHAPE as well as the values

Everything above assumes a fixed set of fields. A document store does not give you one, and
the discipline has to census the shape itself. Where the source is documents, or the
destination is:

- **Field ABSENCE is data, and it is not the same as null.** In a table every row has every
  column; in a collection a field can be missing on 30% of documents, and "missing", "null"
  and "empty string" are three different states that a naive transform collapses into one.
  Count each field's presence rate across the whole collection before mapping it, and decide
  per field which of the three the destination should hold.
- **A field's TYPE varies between documents.** The same key holds a string on old documents
  and a number on newer ones, or a single object where later writes put an array. Census the
  distinct types per field, not just the distinct values - a destination with real types
  rejects the minority, and one without silently stores both.
- **Embedded collections are the grain**, and they are where the flattening defect lives. An
  array that loses a member is invisible to every document count: the document is present,
  its identifier matches, and one order or one line item is gone. Assert the LENGTH of every
  embedded array on both sides, per document.
- **Denormalized copies must ALL be updated.** Without joins, the same customer name may be
  embedded in a thousand order documents. Fixing the customer record fixes nothing the reader
  sees. Enumerate every place a value is copied and reconcile each - this is the twin sweep,
  and in a document store it is the normal case rather than the exception.
- **Ordering inside an array is usually meaningful** and is trivially lost by a transform
  that rebuilds rather than copies. Compare arrays as sequences, not as sets, unless you have
  established the order carries no meaning.

`migration_check.py` reads JSONL and JSON as well as CSV, and addresses nested fields by
dotted path (`address.city`), so every check below applies unchanged. Arrays are compared
both as content and as a `field[]` length, which is what catches the lost member.

## Step 1 - derive the contract from the DESTINATION

Read the destination schema and write the contract it actually requires: types, enum
membership, ranges, required-ness, referential integrity, precision (money in minor units,
timezone handling for dates).

**Pin the timezone of every datetime column on both sides, and write it down.** Legacy stores
are routinely naive local time with no offset recorded. A destination column typed with a
zone, or an application assuming UTC, then REINTERPRETS those values instead of converting
them, and every timestamp moves by the offset - uniformly, which reconciles as a formatting
class and is a real shift. DST makes it worse than a constant: the offset depends on each
row's own date, so one correction factor is wrong for half the year. And a date-only value
that crosses midnight changes the BUSINESS date - a posting date, an invoice date, a period
boundary - silently moving the row into a different reporting period. State the source zone
and whether it observes DST, state the destination's storage convention, convert per row with
a zone-aware library rather than an offset constant, and reconcile by value on a row from each
side of a DST boundary and a row at 23:00 and 00:30 local.

**Then enumerate what the destination actually ENFORCES.** This is the step everyone skips.
Enums stored as free text, foreign keys declared without constraints, permissive numeric or
date parsing, implicit truncation - each means the store will accept wrong data and report
success. **The weaker the enforcement, the more the burden of proof sits on your own
validation**, and the less a clean load tells you.

The contract includes what the APPLICATION enforces on its own writes, not just the schema:
a direct load bypasses ORM validation, model defaults, normalization and stamping
(created_by, timestamps). Either replicate those in the transform, or record that migrated
rows are deliberately distinguishable - a decision made on the record, not a gap found
later.

That application layer is code, and intake told you where it is: read the model
definitions, validators and defaults for every table you load, not the schema alone. A
schema that says a status is ten free characters and a model that says it is one of five
choices are two different contracts, and the load has to satisfy the one the application
will read by.

## Step 2 - derive SEMANTICS from behaviour, not names

A field's meaning comes from what the producing system DOES with it, never from what it is
called. A boolean named for success may be set on submission and never cleared on failure.
A timestamp may never be populated. Where two columns disagree, find which one the legacy
system itself treats as authoritative - usually the one its own UI and reports read.

**Where behaviour lives, and how to read it - the same four searches in any stack.** For
each column you will map, find in the code intake located:

- its **WRITERS**: every assignment - the model save, the raw SQL write, the scheduled job,
  the stored procedure. Each writer is a candidate meaning, and a column with two writers
  that disagree is step 2b's contradiction found before a single row is queried.
- its **READERS**: every filter, report, export and screen that consumes it. The reader the
  business reconciles against is the authoritative one. A column no reader consumes is a
  candidate for dropping in step 4, not for mapping.
- its **CONSTANTS**: enum definitions, status vocabularies, magic values, and the format of
  any composite or prefixed identifier - naming conventions live here and nowhere in the
  schema.
- its **VALIDATION**: what the application refuses to write, which is step 1's "what the
  application enforces" seen from the source side.

You are not learning the framework; you are following one column through it, and a text
search is enough. The code tells you what SHOULD have written the column; the census tells
you what DID. Jobs, one-off scripts and years of manual fixes leave rows no current writer
produced, so the writer supplies the hypothesis and the counterexample query below tests
it. Where there is no code to read (rung 2 or 3 at intake), say so at the decision and do
not fill the gap with the name.

For any field whose meaning you inferred rather than observed, that inference is a
HYPOTHESIS - and a hypothesis is testable, so **write the COUNTEREXAMPLE QUERY**: find the
rows where the name predicts one thing and the authoritative field says another. Zero rows
supports the inference; any rows refute it, and the count tells you the blast radius.

This is the single cheapest check in the whole loop. "Is this flag really what it says?"
becomes `WHERE looks_successful = 1 AND authoritative_status IN (<failure states>)` - one
query, an exact number, no opinion, in seconds, before a single row is migrated.

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

**A tenant-scoped key is not a key.** Where the source scopes ids or numbers per tenant, per
company or per branch, the join key is the PAIR (tenant, key) and nothing else. Joining on the
bare key attaches one tenant's rows to another's at full row count with no error, and unlike
everything else in this file that one is a disclosure incident rather than a wrong number. It
also poisons the census: `GROUP BY key HAVING COUNT(*) > 1` flags a sound per-tenant key as
ambiguous and sends clean rows into the deferred pile. Group by the pair, and carry the tenant
predicate into every join, every reconciliation query and every delete in the load.

Validate each key against an **independent human-readable attribute** - a name, a document
number, a natural key - and state the match rate.

**Normalize both sides yourself, and report the match rate BOTH ways.** The two systems do not
share a comparison rule: a case- and accent-insensitive collation matches "ABC Corp", "abc
corp" and "ABC Corp " where the same comparison in your transform language does not, and
trailing spaces are significant in some engines and ignored in others. Compare raw, then
compare case-folded and trimmed, and report both numbers. The GAP between them counts the rows
whose match depends on a rule the two systems do not agree on - each one either a false miss
you are about to defer or a false merge attaching two real entities to one row, and which it is
gets decided by looking at them, not by picking a collation.

A wrong key does not fail loudly: it
produces a complete-looking result in which every row is attached to the wrong entity, and
that is indistinguishable from success without this check.

**A sentinel in the KEY column force-maps everything to one value.** The worst bad join is
not a missing key, it is a placeholder that LOOKS like one. An extract that renders NULLs as
the literal text `"NULL"`, or a legacy default of `"0"` / `"000"`, becomes a real map key:
every record with no true key collides on it and is force-mapped to one arbitrary value, at
full row count, with no error anywhere. Filter the extract at the SOURCE
(`WHERE key IS NOT NULL AND key NOT IN (<junk set>)`) rather than downstream, and when you
build a key-to-value map, dedup to the single REAL value - otherwise last-seen-wins quietly
decides, and a placeholder shadows the real one.

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
3. **Find the ambiguous rows a DIFFERENT key path** - usually not a coarser grain of the
   key that just failed. When the ambiguity comes from placeholders, those rows have no
   usable key at all, so there is nothing to re-join more loosely; what they need is
   another route from source to destination entirely, typically through an owning entity
   that both systems identify unambiguously. That is a new source-to-destination key
   chain, and it earns its OWN pass through this step - its own uniqueness check and its
   own match rate against an independent attribute. Inheriting confidence from the first
   key path is exactly the mistake this step exists to prevent.
4. **Report the deferred count as part of coverage.** A phase you named is a decision; a
   phase you silently dropped is the "it ran clean over a subset" failure wearing a
   different hat.

## Step 3b - decide the FALLBACK for values that cannot be mapped

The census finds values with nowhere to land: outside the destination's enum, malformed,
or absent. Finding them is not the decision. What happens to those rows is, and left
unstated it gets made row-by-row by whatever the code does when a lookup misses - usually
NULL, or a default nobody chose.

- **Treat SENTINELS as missing, not as data.** A placeholder where a name belongs, a
  synthesized address, a zero that means "not calculated yet" rather than zero: each migrates
  cleanly and is wrong, because nothing downstream can tell it from a real value. Enumerate
  the sentinels the source actually uses during the census, and decide per column whether each
  becomes NULL, a fallback, or a counted skip.
- **Count the affected rows before choosing.** A fallback applied to nine rows and one
  applied to nine thousand are different decisions, and the count is what tells you which
  one you are making.
- **Prefer DERIVING the value from an authoritative related record over a constant** - but
  only where the parent's value is the one that was true WHEN THE CHILD WAS WRITTEN. It is
  wrong the moment the parent is mutable and the child is a point-in-time record: an invoice,
  a ledger entry, a statement, anything a person will later read as a record of what was true
  on its date. Inheriting the CURRENT address, rate or owner onto a 2019 document rewrites
  history, and that is worse than a constant, because it looks authoritative and re-derives to
  the same wrong answer every time anyone checks it. Ask first whether the parent's field has
  a history - an audit table, an effective-dated row, a superseded record - and if it does,
  join on the child's date. If it does not, the value is not recoverable: take a marked
  fallback or a counted skip, and say which. A
  child row missing a dimensional value can often inherit it from its parent, which is
  both more likely correct and re-derivable later. A hardcoded default is unfalsifiable
  after the fact: nothing distinguishes a row that genuinely held that value from a row
  that fell back to it.
- **Mark fallen-back rows so they stay identifiable**, or record their keys. Otherwise the
  decision dissolves into the data and cannot be revisited when someone asks how many rows
  were guessed.
- **Never let unmappable mean silently skipped.** Every row is transformed, deliberately
  fallen back, or skipped with a counted reason. Those three must sum to the input.

This step is cheap at design time and awkward to retrofit: marking and counting fallbacks
is a line of code before the transform is written and a re-review afterwards. If you reach
it late, the count is what lets you choose honestly - a small, non-money-bearing fallback
set can be an ACCEPTED untraceability, recorded as such with its number, while a large or
money-bearing one is worth the retrofit. Deciding that is legitimate; leaving it unstated
is not.

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

**Fix the comparison rule before you run the comparison, or the reconciliation reports its
own artifacts.** Compare money as integers in minor units; never float equality, and never a
DECIMAL against a DOUBLE. Normalize both sides identically (trim, case, NULL versus empty
string) and state which normalizations you applied, because each one is a difference you have
decided not to see. Report the summed signed difference as well as the row count: a
one-cent-per-row truncation over two million rows is $20,000 that a mismatch count never shows.

**A UNIFORM mismatch class is the dangerous one.** Differences sharing a sign, a magnitude, a
factor or a constant offset are a systematic transform defect - truncation where the source
rounds, minor units against major, a timezone shift - not noise. "Explain each class" means
naming the line of the transform that produces it and why that behaviour is correct. A class
you can only describe is a class you have not explained.

This is also how a denormalized or summary field is caught drifting from the records it
summarises: derive the value from the authoritative rows, compare against the stored one
across the whole population, and emit a backfill for the difference.

## Step 6 - scope the load, and protect what the destination OWNS

A destination accumulates rows the source never had: users, roles, permissions, settings,
anything created after cut-over. **A reload scoped to "all tables" destroys them.** Scope
every load to the tables the transform owns, and name the excluded tables explicitly.

**Check what is IN-FLIGHT before a bulk mutation on a shared path.** A record another
process depends on in its CURRENT state - a batch awaiting a response, a job mid-retry,
anything a downstream system has already been told about - must not be advanced underneath
it. The transform is correct in isolation and still breaks the system, which is exactly why
a row-level review never catches it. Identify the in-flight states before the write and
exclude them.

**Know what the destination DOES on write before a bulk load.** Triggers, webhooks,
notification sends, audit hooks, denormalized recomputes: a load that fires per-row side
effects is an incident, not a migration - two million rows can be two million emails.
Enumerate the write-path side effects, disable or route around them deliberately, and
re-enable afterwards, with both halves on the record.

Those side effects are in the destination's CODE, at two layers: the application's write
path (model hooks, signal receivers, queue publishers, denormalized recomputes) and the
store's own (triggers, foreign-key actions). A direct load bypasses the first layer and
still fires the second, so read both for every table you load - intake told you where -
and list what fires before choosing the load path.

**Reset the destination's id sequences after loading explicit keys.** Auto-increment and
sequence counters do not follow explicit inserts everywhere; the first application insert
after cut-over collides with a migrated id. No check on the migrated data can see this
defect - it lives in FUTURE rows - so it has to be a step, not a finding.

Destructive operations get a restore path proven BEFORE they run, not discovered after - and
the restore has to be SCOPED the way the load was. A point-in-time restore of the whole
database is the "all tables" mistake pointed backwards: it reverses every application write and
every destination-owned row created since the timestamp, which on a live destination is real
users' work, including the tables the top of this section told you to protect. Prove a restore
of exactly the tables the transform owns - snapshot those before the load, restore those. If
the destination is live and taking writes, roll-FORWARD is the only available direction: say so
before the first batch, not after one fails.

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
- **Across two systems, the progress record cannot live with the source.** That forks the
  problem. If the load can be made IDEMPOTENT on a key observable in the DESTINATION alone
  - does this row already exist, judged without consulting the source - then resume is
  cheap: re-run it and the completed rows skip themselves, with no checkpoint state at all.
  Two conditions, and both must hold or the resume silently loses rows. The existence check
  must be at the grain of the whole UNIT OF WORK, not of the first row written: a parent
  inserted ahead of its children makes the parent's presence say "done" while the children are
  gone, at a clean parent count. And each unit must be written in ONE transaction, so a killed
  batch leaves it wholly present or wholly absent - existence cannot tell a complete row from
  one a kill caught half-populated. Where the unit spans tables, key the check on the LAST
  write and wrap the unit. If it cannot -
  an UPDATE, or an insert with no natural destination-side key - then it is materially
  harder, because you must persist which source rows were applied AS A TABLE IN THE
  DESTINATION. Decide which of those two you are in before the first batch runs.
- **Watch for column constraints that abort the BATCH, not the row.** An unsigned column
  meeting a negative value, or a value exceeding a width, can fail the entire statement -
  clamp or validate before the write, and know which failures are per-row and which are
  fatal to the batch.
- **Declare the CHARACTER SET at every hop, the way you declare the columns.** A census of
  the source cannot detect damage the TRANSFER does: the source column's charset, the client
  connection's charset, the file's encoding and the load statement's charset clause are four
  separate settings, and any one left to a default turns an accented character into mojibake
  or a `?` on the way through. Round-trip one known non-ASCII row end to end over the real
  channel before the bulk run and compare it BYTE for byte - a terminal rendering both the
  same is not evidence.
- **Name the columns in every load statement.** A positional LOAD/COPY silently shears when
  the file and the table disagree on column order: every value lands, every count
  reconciles, and each field holds its neighbour's data. Explicit column lists are one
  line of ceremony against a whole-table defect.
- **Plan the DELTA before the load, not after.** Everything created in the source after the
  snapshot is invisible to it (see Reach). Either freeze the source for the window - and
  say so - or name a delta pass that re-runs this same loop over rows created since, and
  reconcile AFTER cut-over against the frozen source: that is the one moment both sides
  are supposed to be equal.

**Keep schema (DDL) and data (DML) as separate migrations.** They have different risk,
different rollback, and different rehearsal needs; bundling them means a data defect forces
a schema rollback. And once a migration has been APPLIED anywhere, treat it as immutable -
correct it with a new one rather than editing history that other environments already ran.

## Step 6c - a defect found in one row is a CLASS

A migrated row reported wrong is a SIGNATURE, not a scope. Write the predicate that selects
it - the condition that makes that row wrong - run it over the whole table, and fix every
match. Closing on the reported row leaves the rest of its class live, and the next report is
drawn from exactly the population you left behind.

The evidence is that the class is EMPTY: the count of still-matching rows is zero. Not that
the reported row is now right. If you deliberately fix a subset, that needs sign-off naming
what is excluded and why, agreed before you close rather than after.

## Step 7 - close out

The receipt is the destination-side evidence, not the run log:
- the contract asserted, and what the destination does/does not enforce
- key uniqueness + match-rate against an independent attribute, and the count of rows
  deferred as ambiguous rather than matched by guess
- the coverage census (in scope / transformed / skipped + reasons), and the count of rows
  that took a fallback rather than a mapped value
- the full-population value reconciliation (mismatch count)
- spot checks BY VALUE on representative LEGACY and edge rows, not only freshly-created ones
- the evidence rung each side was on (code / running system / schema only), and which
  decisions were BLOCKED rather than guessed because of it
- the migration brief, updated with what this run learned

A migration that cannot show these has not been verified - it has been run. Take the
honest downgrade rather than calling it done.

## Running the mechanical checks

Most of this loop is judgment. The mechanical minority is not - each of those checks is a
query whose answer is a number, and they are executable. They live in `migration_check.py`,
beside this file:

```bash
python3 migration_check.py --spec spec.json
```

Declare only what applies; each section is optional - but what you DECLARE is validated: an
unknown section, contract type, or rule key is a spec error (exit 2), never a silent skip,
because a typo'd check is a check that never runs while the run looks green. It checks
**mutually-exclusive state precedence** (did the transform let the right flag win - and
every affected row the destination never received is counted and fails, unless an
`allow_missing` allowance declares the skips deliberate), **key uniqueness on BOTH sides**
(a natural key mapping N:1, a blank/sentinel key, and - on the destination - a
double-applied load minting duplicates), **key identity** (match rate against an
independent attribute, with the threshold explicit in the spec and 1.0 by default),
**value reconciliation** (the landed values compared against the source row by row over
the full population - step 5, executable; blank or duplicated destination keys are
excluded and counted, never resolved last-seen-wins), **column coverage** (every source
column mapped / dropped / defaulted), **coverage summation** (transformed + skipped +
deferred must equal the input), **grain** (children-per-parent in both directions,
catching collapse AND fan-out), the **destination contract** (int/number/ISO-date/enum,
required, min/max, all-NULL), your **counterexample queries** (an inferred meaning is a
hypothesis), and **provenance** (an artifact older than the data it maps is stale by
construction - and an entry missing a date, or carrying a non-ISO one, fails rather than
silently passing). A declared input with ZERO rows is a block too, unless `allow_empty`
says it is deliberate - an empty extract is the wrong-WHERE clause wearing a clean run.

**It tells you what it did NOT check.** Every section is optional, so a spec declaring
almost nothing prints an unbroken column of `ok` and looks identical to a thorough run. Each
undeclared section is therefore printed as `NOT RUN` with the cost of its absence, and the
summary carries the count. Declining a check is legitimate - many sections do not apply to a
given migration - but that has to be a visible decision rather than one inferred from silence.

That is also the boundary of what any tool can enforce here. It cannot know whether your
precedence rule is right, whether the census was thorough, or whether the fallback you chose
is sane. It can only know whether you declared one. **Presence of a decision is enforceable;
its correctness is not** - and pretending otherwise would be the same green-on-wrong trap the
rest of this file exists to prevent.

**The escape hatches, and what declaring one costs you.** Every check that can block has a
declared way past it, because a checker that cannot express a legitimate exception gets
switched off entirely. Each is a claim you are making, recorded in the output:

| declare | means | use when |
|---|---|---|
| `key.allow_missing: N` | up to N source rows legitimately never reached the destination | a scoped or phased load, soft deletes excluded |
| `key.allow_unmatched: N` | up to N destination rows legitimately have no source row | rows the destination generates itself |
| `key.identity.min_match_rate` | a match rate below 1.0 is acceptable | almost never - a partial match means some rows are on the wrong entity |
| `counterexamples[].allow_no_match` | the hypothesis genuinely does not arise in this data | after checking it is not a value mismatch (`"1"` against a column holding `"true"`) |
| `contract[col].sentinels: false` | this column's sentinel-looking values are real | `"NA"` is Namibia, not "not applicable" |
| `coverage.skipped` / `deferred` | this many rows were deliberately not transformed | any partial load, always with the reason written down |
| `allow_empty` | an empty input is expected | almost never - an empty extract passes every check by having nothing to fail |

Declaring one is legitimate. Setting it to a number that makes the check unfalsifiable is the
same thing as deleting the check, and the output prints the value so a reviewer can see which
you did.

Exit codes: **0** = every declared check passed; **1** = a check FAILED - a block, because
the transform is not proven; **2** = the spec itself is invalid. CSV in, so it runs against
an extract, in CI, or against a fixture with no database driver.

**Run the CHECKS before the extract; the script is a backstop, not the first line.** These
are a discipline first and a script second, and the moment they pay is BEFORE you trust an
extract - run them on the source however you can query it, in its own dialect, on whatever
channel reaches it. Waiting for a CSV inverts the order: by the time you have one you have
already decided which rows and columns to pull, which is exactly what uniqueness, identity
and coverage were supposed to inform. That ordering matters most in the case the script
cannot serve at all - two systems behind different drivers and different channels, where no
single connection spans both. The script stays deliberately EXTRACT-based for that reason - it reads CSV, JSONL or JSON and never connects to anything. A
live-connection mode would need a driver per store, would still not span two of them, and
would cost the property that lets this run anywhere with nothing installed.

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

# Red-team protocol

The skill's claim is that a verifier following it finds defects that reconcile clean and are
still wrong. The way to test that claim without the author grading their own work is three
separated roles:

1. **Builder** (deterministic): `gen_source.py` produces a realistic legacy source (SQLite
   standing in for MySQL) whose mess is CONSISTENT with the legacy code's semantics;
   `transform_gold.py` produces the correct destination from it. Both are in this directory.
   The legacy and destination application code trees are the ones used in the skill's fixture
   scenarios (a PHP billing app and a Python platform).
2. **Red team** (an agent that has read the skill): receives the lab, the correct transform and
   the list of defect classes the skill already names, and plants ten defects - at least six
   OUTSIDE the named classes, the rest built to EVADE a named check. It may edit the transform so
   the script and the data agree on each wrong answer. It seals the answer key (id, mechanism,
   exact predicate, row count, why wrong, what it evades) where the verifier cannot read it, and
   records the destination hash.
3. **Verifier** (an agent following the skill cold): gets only the lab - source, destination,
   the transform "as run", both code trees, a README with the ask - with both databases
   queryable. It produces a receipt: findings with predicates and counts, the five receipt
   lines, what it did not check.

Scoring is receipt against key: found, found but hedged, missed, false positive. A miss is the
honest output and becomes either a line in SKILL.md or a documented limit.

The red team and the verifier are instances of the same model, so "unknown" means unknown to
the skill, not unknowable to the model. That is still the claim under test: whether the
discipline finds what its author did not enumerate.

Rounds are recorded under `rounds/`.

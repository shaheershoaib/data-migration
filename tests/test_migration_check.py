"""The mechanical migration checks, against a fixture seeding one instance of each
defect class that actually shipped to production looking like success.

Two obligations, and the second matters as much as the first:
  1. every seeded defect is CAUGHT (no escapes)
  2. a clean migration produces ZERO findings (no false blocks) - a checker that
     cries wolf gets switched off, and then there is no checking at all.
"""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHECK = os.path.join(os.path.dirname(HERE), "migration_check.py")
FIX = os.path.join(HERE, "fixtures")


def run(spec):
    r = subprocess.run([sys.executable, CHECK, "--spec", os.path.join(FIX, spec), "--json"],
                       capture_output=True, text=True)
    return json.loads(r.stdout), r.returncode


def by_name(results, name):
    return next(x for x in results["results"] if x["check"] == name)


class DefectsAreCaught(unittest.TestCase):
    """Each assertion below is a defect that reached production undetected."""

    @classmethod
    def setUpClass(cls):
        cls.res, cls.code = run("spec_bad.json")

    def test_the_run_blocks(self):
        self.assertEqual(self.code, 1, "a failing check must be a BLOCK, not a warning")

    def test_re_keyed_migration_is_caught_by_identity_not_by_counts(self):
        # row counts reconcile; the key attaches rows to the WRONG entity
        r = by_name(self.res, "key-identity")
        self.assertFalse(r["ok"])
        self.assertLess(r["match_rate"], 1.0)

    def test_column_never_carried_is_caught(self):
        # every row moves, a field is silently absent - invisible to a row census
        r = by_name(self.res, "column-coverage")
        self.assertFalse(r["ok"])
        self.assertIn("status", r["unaccounted"])

    def test_grain_collapse_is_caught(self):
        # one-to-many flattened to one-to-one; counts still look plausible
        r = by_name(self.res, "grain")
        self.assertFalse(r["ok"])
        self.assertEqual(r["source_max_per_parent"], 2)
        self.assertEqual(r["destination_max_per_parent"], 1)

    def test_destination_contract_violations_are_caught(self):
        # a weakly-enforcing store accepts every one of these without an error
        r = by_name(self.res, "destination-contract")
        self.assertFalse(r["ok"])
        cols = {c["column"] for c in r["failing_columns"]}
        self.assertEqual(cols, {"amount", "delivered_at", "state"},
                         "non-numeric money, an all-NULL column and an out-of-enum value")

    def test_semantic_drift_is_caught_by_the_counterexample_query(self):
        # a flag whose NAME promises success, set on submit and never cleared on failure
        r = by_name(self.res, "counterexamples")
        self.assertFalse(r["ok"])
        self.assertEqual(r["cases"][0]["contradicting_rows"], 2)

    def test_stale_supplied_artifact_is_caught(self):
        # an artifact older than the data it maps cannot know about anything created since
        r = by_name(self.res, "provenance")
        self.assertFalse(r["ok"])
        self.assertEqual(len(r["stale"]), 1)


class NonUniqueNaturalKey(unittest.TestCase):
    def test_n_to_one_natural_key_is_caught(self):
        # resolving by the string silently picks whichever row it hits first
        res, code = run("spec_natkey.json")
        r = by_name(res, "key-uniqueness")
        self.assertFalse(r["ok"])
        self.assertIn("AA", r["examples"])
        self.assertEqual(code, 1)


class CleanMigrationIsNotBlocked(unittest.TestCase):
    """The false-block guard. As important as the catches."""

    def test_zero_findings_and_exit_zero(self):
        res, code = run("spec_ok.json")
        self.assertEqual(res["failed"], 0, "a correct migration must not be flagged")
        self.assertEqual(code, 0)

    def test_every_check_actually_ran(self):
        # a green run because nothing executed would be the worst outcome
        res, _ = run("spec_ok.json")
        ran = {r["check"] for r in res["results"]}
        self.assertEqual(ran, {"row-census", "key-uniqueness", "key-identity",
                               "column-coverage", "grain", "destination-contract",
                               "provenance"})



class MutuallyExclusiveFlags(unittest.TestCase):
    """Two contradictory flags on one row, and which one the transform let win.

    The shape: a success flag written when an operation is SUBMITTED and never cleared
    when it later fails, sitting alongside the status that records the real outcome.
    Reading the flag instead of the status migrates failures as successes - and the
    result looks complete, which is why it survives review.
    """

    def test_source_contradictions_are_reported_but_do_not_fail_on_their_own(self):
        # the mess belongs to the legacy data, not to the transform
        res, _ = run("spec_conflict_resolved.json")
        c = by_name(res, "exclusivity-precedence")["cases"][0]
        self.assertEqual(c["source_contradictions"], 2)
        self.assertTrue(c["ok"], "correctly resolved contradictions must not fail")

    def test_resolving_against_precedence_is_caught(self):
        res, code = run("spec_conflict.json")
        c = by_name(res, "exclusivity-precedence")["cases"][0]
        self.assertEqual(c["precedence_violations"], 2)
        self.assertFalse(c["ok"])
        self.assertEqual(code, 1)

    def test_the_finding_names_the_row_and_both_values(self):
        # a count alone is not actionable; you need the key and what it should have been
        res, _ = run("spec_conflict.json")
        ex = by_name(res, "exclusivity-precedence")["cases"][0]["examples"][0]
        self.assertEqual(ex["expected"], "REVERSED")
        self.assertEqual(ex["got"], "SETTLED")
        self.assertIn("reversed", ex["matched"])
        self.assertIn("settled", ex["matched"])

    def test_a_row_with_only_one_state_still_gets_verified(self):
        # row 4 is REVERSED-only and correct; the check must cover non-conflicting rows too
        res, _ = run("spec_conflict.json")
        self.assertEqual(by_name(res, "exclusivity-precedence")["cases"][0]["rows_checked"], 4)
if __name__ == "__main__":
    unittest.main()

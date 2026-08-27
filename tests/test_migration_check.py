"""The mechanical migration checks, against a fixture seeding one instance of each
defect class that actually shipped to production looking like success.

Two obligations, and the second matters as much as the first:
  1. every seeded defect is CAUGHT (no escapes)
  2. a clean migration produces ZERO findings (no false blocks) - a checker that
     cries wolf gets switched off, and then there is no checking at all.
"""
import itertools
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHECK = os.path.join(os.path.dirname(HERE), "migration_check.py")
FIX = os.path.join(HERE, "fixtures")
TMP = tempfile.mkdtemp(prefix="migration_check_test_")
_seq = itertools.count()


def F(name):
    """Absolute fixture path, for specs written outside the fixtures directory."""
    return os.path.join(FIX, name)


def run_path(spec_path, json_out=True):
    args = [sys.executable, CHECK, "--spec", spec_path] + (["--json"] if json_out else [])
    r = subprocess.run(args, capture_output=True, text=True)
    out = json.loads(r.stdout) if json_out and r.stdout.strip().startswith("{") else None
    return out, r


def run(spec):
    out, r = run_path(os.path.join(FIX, spec))
    return out, r.returncode


def run_dict(spec_dict, json_out=True):
    p = os.path.join(TMP, "spec_%d.json" % next(_seq))
    with open(p, "w", encoding="utf-8") as f:
        json.dump(spec_dict, f)
    return run_path(p, json_out)


def write_csv(name, text):
    p = os.path.join(TMP, "%d_%s" % (next(_seq), name))
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


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

    def test_a_blank_key_is_a_sentinel_not_a_key(self):
        # one keyless row cannot join; as a map key it force-maps onto one arbitrary value
        res, r = run_dict({"source": F("legacy_blank_key.csv"),
                           "destination": F("new_ok.csv"),
                           "key": {"source": "id", "destination": "legacy_id"}})
        u = by_name(res, "key-uniqueness")
        self.assertFalse(u["ok"])
        self.assertEqual(u["blank_key_rows"], 1)
        self.assertEqual(r.returncode, 1)


class DoubleLoadIsCaught(unittest.TestCase):
    """A non-idempotent load applied twice: every value right, every row twice.
    Row counts, source-key uniqueness, identity, coverage and contract all pass -
    this shipped green until the destination side of the key was checked too."""

    @classmethod
    def setUpClass(cls):
        cls.res, cls.r = run_dict({
            "source": F("legacy_ok.csv"), "destination": F("new_ok_doubled.csv"),
            "key": {"source": "id", "destination": "legacy_id",
                    "identity": {"source": "name", "destination": "name"}},
            "columns": {"mapped": {"id": "legacy_id", "name": "name",
                                   "customer_id": "customer_id",
                                   "amount": "amount", "state": "state"}},
            "reconcile": {},
            "grain": {"source_parent": "customer_id", "destination_parent": "customer_id"}})

    def test_destination_key_uniqueness_catches_it(self):
        u = by_name(self.res, "key-uniqueness-destination")
        self.assertFalse(u["ok"])
        self.assertEqual(u["duplicate_values"], 2)
        self.assertEqual(self.r.returncode, 1)

    def test_grain_fanout_catches_it_too(self):
        g = by_name(self.res, "grain")
        self.assertFalse(g["ok"])
        self.assertEqual(g["parents_gaining_rows"], 2)

    def test_reconciliation_refuses_to_vouch_for_ambiguous_keys(self):
        # duplicated destination keys are EXCLUDED, never resolved last-seen-wins -
        # so nothing gets compared, and a zero-row comparison is not a pass
        v = by_name(self.res, "value-reconciliation")
        self.assertEqual(v["rows_compared"], 0)
        self.assertFalse(v["ok"])


class ValueCorruptionIsCaught(unittest.TestCase):
    """The flagship check: a mapped column whose VALUES silently diverged (amounts x10).
    Counts, keys, identity, coverage, grain and contract are all clean - only comparing
    the landed values against the source, row by row, sees it (step 5, executable)."""

    def test_corrupted_values_fail_reconciliation(self):
        res, r = run_dict({
            "source": F("legacy_ok.csv"), "destination": F("new_value_bad.csv"),
            "key": {"source": "id", "destination": "legacy_id",
                    "identity": {"source": "name", "destination": "name"}},
            "columns": {"mapped": {"id": "legacy_id", "name": "name",
                                   "customer_id": "customer_id",
                                   "amount": "amount", "state": "state"}},
            "reconcile": {"columns": ["amount"]}})
        self.assertTrue(by_name(res, "key-identity")["ok"],
                        "identity is clean - reconciliation must be what catches this")
        v = by_name(res, "value-reconciliation")
        self.assertFalse(v["ok"])
        self.assertEqual(v["mismatched_values"], 2)
        self.assertEqual(v["mismatches_by_column"], {"amount": 2})
        self.assertEqual(r.returncode, 1)

    def test_numeric_normalization_is_not_a_false_block(self):
        # "150" and "150.0" are the same amount; a checker that flags them gets switched off
        src = write_csv("s.csv", "id,amount\n1,150\n")
        dst = write_csv("d.csv", "legacy_id,amount\n1,150.0\n")
        res, r = run_dict({"source": src, "destination": dst,
                           "key": {"source": "id", "destination": "legacy_id"},
                           "columns": {"mapped": {"id": "legacy_id", "amount": "amount"}},
                           "reconcile": {"normalize": ["number"]}})
        self.assertTrue(by_name(res, "value-reconciliation")["ok"])
        self.assertEqual(r.returncode, 0)


class SpecTyposAreErrorsNotSilentSkips(unittest.TestCase):
    """A green run because nothing executed would be the worst outcome. A typo'd
    section or type must be a loud spec error (exit 2), never an ignored key."""

    def test_unknown_section_is_a_spec_error(self):
        # "counterexample" (singular) used to be silently ignored - a check that
        # never ran, on a run that looked green
        _, r = run_dict({"source": F("legacy_ok.csv"), "destination": F("new_ok.csv"),
                         "counterexample": [{"name": "typo'd section",
                                             "source_when": {"state": "ACTIVE"},
                                             "contradicted_by": {"state": ["ACTIVE"]}}]})
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown spec section", r.stderr)

    def test_unknown_contract_type_is_a_spec_error(self):
        _, r = run_dict({"destination": F("new_ok.csv"),
                         "contract": {"amount": {"type": "numeric"}}})
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown type", r.stderr)

    def test_reconcile_without_key_and_mapping_is_a_spec_error(self):
        _, r = run_dict({"source": F("legacy_ok.csv"), "destination": F("new_ok.csv"),
                         "reconcile": {}})
        self.assertEqual(r.returncode, 2)


class ContractTypesHaveTeeth(unittest.TestCase):
    def test_declared_date_type_actually_validates(self):
        # "type": "date" was documented and silently unimplemented - "banana" passed it
        res, r = run_dict({"destination": F("new_bad_dates.csv"),
                           "contract": {"delivered_at": {"type": "date", "required": True}}})
        c = by_name(res, "destination-contract")
        self.assertFalse(c["ok"])
        rules = {v["rule"] for col in c["failing_columns"] for v in col["violations"]}
        self.assertIn("date", rules)
        self.assertEqual(r.returncode, 1)

    def test_iso_dates_pass(self):
        dst = write_csv("d.csv", "legacy_id,delivered_at\n1,2026-01-02\n2,2026-01-02T03:04:05\n")
        res, r = run_dict({"destination": dst,
                           "contract": {"delivered_at": {"type": "date", "required": True}}})
        self.assertTrue(by_name(res, "destination-contract")["ok"])
        self.assertEqual(r.returncode, 0)

    def test_int_rejects_a_float(self):
        # "3.5" parsing as an int-typed column is the permissive parsing the contract
        # step exists to catch
        dst = write_csv("d.csv", "legacy_id,qty\n1,3.5\n")
        res, _ = run_dict({"destination": dst, "contract": {"qty": {"type": "int"}}})
        self.assertFalse(by_name(res, "destination-contract")["ok"])

    def test_max_bound_is_enforced(self):
        dst = write_csv("d.csv", "legacy_id,pct\n1,150\n")
        res, _ = run_dict({"destination": dst, "contract": {"pct": {"type": "number", "max": 100}}})
        self.assertFalse(by_name(res, "destination-contract")["ok"])


class MissingRowsAreCountedNotSkipped(unittest.TestCase):
    """A transform that DROPS the affected rows entirely must not pass the check that
    exists to catch mis-resolving them - silently-skipped is the defect, not a default."""

    def test_exclusivity_fails_when_affected_rows_never_landed(self):
        res, r = run_dict({
            "source": F("legacy_conflict.csv"), "destination": F("new_conflict_partial.csv"),
            "exclusivity": [{"name": "reversal beats settle-flag",
                             "key": {"source": "id", "destination": "legacy_id"},
                             "destination_column": "status",
                             "states": [
                                 {"name": "reversed", "when": {"payment_state": "REVERSED"},
                                  "destination_value": "REVERSED"},
                                 {"name": "settled", "when": {"is_settled": "1"},
                                  "destination_value": "SETTLED"}]}]})
        c = by_name(res, "exclusivity-precedence")["cases"][0]
        self.assertEqual(c["missing_in_destination"], 3)
        self.assertFalse(c["ok"])
        self.assertEqual(r.returncode, 1)

    def test_a_declared_allowance_is_a_decision_not_a_skip(self):
        res, r = run_dict({
            "source": F("legacy_conflict.csv"), "destination": F("new_conflict_partial.csv"),
            "exclusivity": [{"name": "reversal beats settle-flag", "allow_missing": 3,
                             "key": {"source": "id", "destination": "legacy_id"},
                             "destination_column": "status",
                             "states": [
                                 {"name": "reversed", "when": {"payment_state": "REVERSED"},
                                  "destination_value": "REVERSED"},
                                 {"name": "settled", "when": {"is_settled": "1"},
                                  "destination_value": "SETTLED"}]}]})
        self.assertTrue(by_name(res, "exclusivity-precedence")["ok"])
        self.assertEqual(r.returncode, 0)

    def test_identity_reports_source_rows_the_destination_never_received(self):
        dst = write_csv("d.csv", "legacy_id,name\n201,Delta LLC\n")
        res, _ = run_dict({"source": F("legacy_ok.csv"), "destination": dst,
                           "key": {"source": "id", "destination": "legacy_id",
                                   "identity": {"source": "name", "destination": "name"}}})
        self.assertEqual(by_name(res, "key-identity")["missing_in_destination"], 1)


class EmptyExtractIsBlocked(unittest.TestCase):
    """The classic wrong-WHERE extract: zero rows, and every downstream check passes
    by having nothing to fail on."""

    def test_an_empty_declared_input_fails_the_census(self):
        res, r = run_dict({"source": F("empty.csv"), "destination": F("new_ok.csv"),
                           "key": {"source": "id", "destination": "legacy_id"},
                           "columns": {"mapped": {"id": "legacy_id", "name": "name",
                                                  "customer_id": "customer_id",
                                                  "amount": "amount", "state": "state"}}})
        c = by_name(res, "row-census")
        self.assertFalse(c["ok"])
        self.assertIn("source", c["empty_inputs"])
        self.assertEqual(r.returncode, 1)

    def test_allow_empty_is_an_explicit_decision(self):
        res, r = run_dict({"source": F("empty.csv"), "destination": F("new_ok.csv"),
                           "allow_empty": True})
        self.assertTrue(by_name(res, "row-census")["ok"])
        self.assertEqual(r.returncode, 0)


class IdentityThresholdIsExplicit(unittest.TestCase):
    def test_default_requires_a_full_match_and_says_so(self):
        # a hardcoded, unprinted 0.99 quietly tolerated 1% wrong-entity attachment
        dst = write_csv("d.csv", "legacy_id,name\n201,Delta LLC\n202,Wrong Name\n")
        res, r = run_dict({"source": F("legacy_ok.csv"), "destination": dst,
                           "key": {"source": "id", "destination": "legacy_id",
                                   "identity": {"source": "name", "destination": "name"}}})
        i = by_name(res, "key-identity")
        self.assertEqual(i["min_match_rate"], 1.0)
        self.assertFalse(i["ok"])
        self.assertEqual(r.returncode, 1)

    def test_a_declared_threshold_relaxes_it_on_the_record(self):
        dst = write_csv("d.csv", "legacy_id,name\n201,Delta LLC\n202,Wrong Name\n")
        res, r = run_dict({"source": F("legacy_ok.csv"), "destination": dst,
                           "key": {"source": "id", "destination": "legacy_id",
                                   "identity": {"source": "name", "destination": "name",
                                                "min_match_rate": 0.5}}})
        i = by_name(res, "key-identity")
        self.assertEqual(i["min_match_rate"], 0.5)
        self.assertTrue(i["ok"])
        self.assertEqual(r.returncode, 0)


class CoverageMustSumToTheInput(unittest.TestCase):
    def test_undeclared_shortfall_fails(self):
        # 4 source rows, 3 landed, nothing declared skipped: the silent subset
        res, r = run_dict({"source": F("legacy_bad.csv"), "destination": F("new_bad.csv"),
                           "coverage": {}})
        c = by_name(res, "coverage-summation")
        self.assertFalse(c["ok"])
        self.assertEqual(c["expected_destination_rows"], 4)
        self.assertEqual(c["destination_rows"], 3)
        self.assertEqual(r.returncode, 1)

    def test_declared_skips_reconcile(self):
        res, r = run_dict({"source": F("legacy_bad.csv"), "destination": F("new_bad.csv"),
                           "coverage": {"skipped": 1}})
        self.assertTrue(by_name(res, "coverage-summation")["ok"])
        self.assertEqual(r.returncode, 0)


class WhenClausesTakeLists(unittest.TestCase):
    def test_a_list_value_means_membership(self):
        res, _ = run_dict({"source": F("legacy_bad.csv"),
                           "counterexamples": [{"name": "failure states, plural",
                                                "source_when": {"status": ["FAILED", "REVERSED"]},
                                                "contradicted_by": {"is_paid": ["1"]}}]})
        c = by_name(res, "counterexamples")
        self.assertFalse(c["ok"])
        self.assertEqual(c["cases"][0]["contradicting_rows"], 2)


class ProvenanceEntriesMustProveSomething(unittest.TestCase):
    def test_a_missing_date_is_a_failure_not_a_pass(self):
        # an entry without data_extracted used to compare "" and silently pass
        res, r = run_dict({"provenance": [{"artifact": "map.csv", "dated": "2026-01-01"}]})
        p = by_name(res, "provenance")
        self.assertFalse(p["ok"])
        self.assertEqual(len(p["invalid"]), 1)
        self.assertEqual(r.returncode, 1)

    def test_non_iso_dates_are_a_failure_not_a_lexicographic_guess(self):
        res, _ = run_dict({"provenance": [{"artifact": "map.csv", "dated": "06/01/2026",
                                           "data_extracted": "05/01/2026"}]})
        self.assertFalse(by_name(res, "provenance")["ok"])


class HumanOutputKeepsFalsyEvidence(unittest.TestCase):
    def test_a_failing_case_prints_its_fields_not_a_truncated_blob(self):
        # nested "cases" checks used to dump one truncated JSON string, cutting off
        # the exact numbers the finding exists to report
        _, r = run_path(os.path.join(FIX, "spec_conflict.json"), json_out=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("precedence_violations: 2", r.stdout)
        self.assertIn("source_contradictions: 2", r.stdout)

    def test_a_zero_match_rate_is_printed_not_elided(self):
        # 0.0 is the most catastrophic value a finding can carry; the old output
        # filter treated it as empty and dropped the line
        dst = write_csv("d.csv", "legacy_id,name\n201,Zulu Corp\n202,Yankee Inc\n")
        p = os.path.join(TMP, "spec_%d.json" % next(_seq))
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"source": F("legacy_ok.csv"), "destination": dst,
                       "key": {"source": "id", "destination": "legacy_id",
                               "identity": {"source": "name", "destination": "name"}}}, f)
        _, r = run_path(p, json_out=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("match_rate: 0.0", r.stdout)


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
        self.assertEqual(ran, {"row-census", "key-uniqueness", "key-uniqueness-destination",
                               "key-identity", "value-reconciliation", "column-coverage",
                               "coverage-summation", "grain", "destination-contract",
                               "counterexamples", "provenance"})

    def test_a_zero_hit_counterexample_is_not_flagged(self):
        res, _ = run("spec_ok.json")
        c = by_name(res, "counterexamples")
        self.assertTrue(c["ok"])
        self.assertEqual(c["cases"][0]["contradicting_rows"], 0)


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


class SilenceIsNotAPass(unittest.TestCase):
    """The strongest check is opt-in, so its ABSENCE has to be visible.

    Without this, a spec that omits `reconcile` prints an unbroken column of `ok` while every
    landed value goes uncompared - the tool's own "zero rows compared is not a pass" rule,
    applied one level up.
    """

    def _spec_without(self, section, destination):
        spec = json.loads(open(F("spec_ok.json"), encoding="utf-8").read())
        spec["destination"] = destination
        spec.pop(section, None)
        path = F("_notrun_%d.json" % next(_seq))
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(spec, fh)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        return path

    def test_undeclared_reconcile_is_announced_not_silent(self):
        path = self._spec_without("reconcile", "new_value_bad.csv")
        _, r = run_path(path, json_out=False)
        self.assertIn("NOT RUN", r.stdout)
        self.assertIn("value-reconciliation", r.stdout)
        # reported, never fatal: not declaring a check is a choice, just a visible one
        self.assertEqual(r.returncode, 0)

    def test_declared_reconcile_produces_no_not_run_line(self):
        _, r = run_path(F("spec_ok.json"), json_out=False)
        self.assertNotIn("NOT RUN", r.stdout)

    def test_json_output_carries_not_run(self):
        path = self._spec_without("reconcile", "new_ok.csv")
        out, _ = run_path(path)
        self.assertEqual([n["check"] for n in out["not_run"]], ["value-reconciliation"])


if __name__ == "__main__":
    unittest.main()

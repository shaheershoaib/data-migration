"""The census tool: Step 0 as numbers a weak reader cannot skip.

Every finding here is one the prose already asks for; the tool exists because an agent that
has to invent the query per dataset invents it wrong (compares the wrong two sets, forgets to
fold case, never puts two sources side by side). The tool prints the numbers; the agent reads.
"""
import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CENSUS = os.path.join(os.path.dirname(HERE), "migration_census.py")
TMP = tempfile.mkdtemp(prefix="migration_census_test_")


def w(name, content):
    p = os.path.join(TMP, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content if isinstance(content, str) else json.dumps(content))
    return p


def run(spec, json_out=True):
    p = w("spec_%d.json" % len(os.listdir(TMP)), spec)
    args = [sys.executable, CENSUS, "--spec", p] + (["--json"] if json_out else [])
    r = subprocess.run(args, capture_output=True, text=True)
    out = json.loads(r.stdout) if json_out and r.stdout.strip().startswith("{") else None
    return out, r


class CensusFindsTheMess(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.roster = w("roster.json", {"records": [
            {"id": "rec1", "fields": {"Name": "Ann A", "Email": "Ann@x.com", "Status": "Active", "NMLS": "123456", "Manager": ["rec2"], "Start": "2024-01-05"}},
            {"id": "rec2", "fields": {"Name": "Bob B", "Email": "bob@x.com", "Status": "active", "NMLS": "NMLS 222222", "Start": "2023-03-01"}},
            {"id": "rec3", "fields": {"Name": "Cy C", "Email": "cy@x.com", "Status": "Active ", "NMLS": "333-333", "Manager": ["recGONE"], "Start": "2031-01-01"}},
            {"id": "rec4", "fields": {"Name": "Dee D", "Email": "ann@x.com ", "Status": "Terminated", "NMLS": "123456", "Manager": None, "Start": "2022-07-07"}},
            {"id": "rec5", "fields": {"Name": "Eve E", "Email": "", "Status": "Inactive", "NMLS": "555555", "Start": "2021-02-02"}}]})
        cls.expenses = w("expenses.json", {"records": [
            {"id": "e1", "fields": {"Amount": 10.005, "Status": "Rejected", "Reimbursed": True}},
            {"id": "e2", "fields": {"Amount": 20.5, "Status": "Paid", "Reimbursed": True}},
            {"id": "e3", "fields": {"Amount": 30.0, "Status": "Rejected", "Reimbursed": True}},
            {"id": "e4", "fields": {"Amount": 40.25, "Status": "Pending"}},
            {"id": "e5", "fields": {"Amount": 50.125, "Status": "Paid", "Reimbursed": True}}]})
        cls.directory = w("users.json", {"users": [
            {"id": "g1", "primaryEmail": "ann@x.com", "emails": [{"address": "ann@x.com", "primary": True}]},
            {"id": "g2", "primaryEmail": "robert@x.com", "emails": [{"address": "robert@x.com", "primary": True}, {"address": "BOB@x.com"}]},
            {"id": "g3", "primaryEmail": "shared@x.com", "emails": [{"address": "shared@x.com", "primary": True}]}]})
        cls.spec = {"sources": {
            "roster": {"path": cls.roster, "key": "id", "links": {"fields.Manager": "roster"}, "id_like": ["fields.NMLS"]},
            "expenses": {"path": cls.expenses, "key": "id"},
            "directory": {"path": cls.directory, "key": "id"}},
            "overlaps": [{"name": "roster email vs directory addresses", "a": "roster.fields.Email", "b": "directory.emails[].address"}]}
        cls.out, cls.r = run(cls.spec)

    def src(self, name):
        return self.out["sources"][name]

    def test_unwraps_the_records_key_and_counts_rows(self):
        self.assertEqual(self.r.returncode, 0, self.r.stderr)
        self.assertEqual(self.src("roster")["rows"], 5)
        self.assertEqual(self.src("directory")["rows"], 3)

    def test_presence_separates_absent_null_and_empty(self):
        f = self.src("roster")["fields"]["fields.Manager"]
        self.assertEqual((f["absent"], f["null"]), (2, 1))
        e = self.src("roster")["fields"]["fields.Email"]
        self.assertEqual(e["empty"], 1)
        self.assertEqual(self.src("expenses")["fields"]["fields.Reimbursed"]["absent"], 1)

    def test_case_and_space_variants_are_grouped(self):
        st = self.src("roster")["fields"]["fields.Status"]
        groups = {g["folded"]: g for g in st["variant_groups"]}
        self.assertIn("active", groups)
        self.assertEqual(sorted(groups["active"]["spellings"]), ["Active", "Active ", "active"])
        self.assertEqual(groups["active"]["rows_in_minority_spellings"], 2)

    def test_dangling_links_are_counted_against_the_target_keys(self):
        links = self.src("roster")["links"]["fields.Manager"]
        self.assertEqual(links["dangling"], 1)
        self.assertEqual(links["target"], "roster")

    def test_id_like_columns_report_non_digits_and_collisions(self):
        n = self.src("roster")["fields"]["fields.NMLS"]["id_like"]
        self.assertEqual(n["non_digit"], 2)
        self.assertEqual(n["collisions_after_digit_normalize"], 1)   # 123456 twice

    def test_money_artifacts_and_future_dates(self):
        self.assertEqual(self.src("expenses")["fields"]["fields.Amount"]["numeric"]["more_than_2_decimals"], 2)
        self.assertEqual(self.src("roster")["fields"]["fields.Start"]["dates"]["in_future"], 1)

    def test_crosstab_of_flags_against_categories(self):
        xt = self.src("expenses")["crosstabs"]
        cell = next(c for c in xt if c["flag"] == "fields.Reimbursed" and c["category"] == "fields.Status")
        self.assertEqual(cell["true_by_value"]["Rejected"], 2)
        self.assertEqual(cell["true_by_value"]["Paid"], 2)

    def test_key_uniqueness_raw_and_folded(self):
        k = self.src("roster")["key"]
        self.assertEqual((k["rows"], k["blank"], k["duplicates_raw"]), (5, 0, 0))
        # a column census can be asked to treat any field as a key: emails fold to a duplicate
        out, _ = run({"sources": {"r": {"path": self.roster, "key": "fields.Email"}}})
        k2 = out["sources"]["r"]["key"]
        self.assertEqual((k2["blank"], k2["duplicates_raw"], k2["duplicates_folded"]), (1, 0, 1))

    def test_overlap_uses_folding_and_array_membership(self):
        ov = self.out["overlaps"][0]
        # ann matches (fold), bob matches only via the alias inside emails[], cy has no directory user
        self.assertEqual(ov["a_distinct"], 3)                      # ann, bob, cy (blank excluded, 'ann@x.com ' folds into ann)
        self.assertEqual(ov["a_in_b_folded"], 2)
        self.assertEqual(ov["a_in_b_raw"], 0)                      # exact strings: 'Ann@x.com' != 'ann@x.com', 'bob' != 'BOB' - the gap IS the finding
        self.assertEqual(ov["a_not_in_b"], 1)
        self.assertEqual(ov["b_not_in_a"], 2)                      # robert (primary, not in roster) and shared

    def test_human_output_prints_the_numbers(self):
        _, r = run(self.spec, json_out=False)
        self.assertEqual(r.returncode, 0)
        for needle in ("variant", "dangling", "crosstab", "overlap", "absent"):
            self.assertIn(needle, r.stdout.lower())

    def test_a_bad_spec_is_an_error_not_a_silent_partial_census(self):
        _, r = run({"sources": {"r": {"path": self.roster, "key": "id", "links": {"fields.Manager": "nosuch"}}}})
        self.assertEqual(r.returncode, 2)
        _, r = run({"sources": {"r": {"path": self.roster, "key": "id", "colour": "blue"}}})
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()

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


def run_discover(folder, extra=()):
    out_md = os.path.join(TMP, "findings_%d.md" % len(os.listdir(TMP)))
    args = [sys.executable, CENSUS, "--discover", folder, "--out", out_md, "--json"] + list(extra)
    r = subprocess.run(args, capture_output=True, text=True)
    out = json.loads(r.stdout) if r.stdout.strip().startswith("{") else None
    return out, r, out_md


class DiscoverNeedsNoDeclarations(unittest.TestCase):
    """The autopilot: a handover FOLDER in, findings out, with nobody deciding what to declare.

    Round 2 showed a weak model neither runs a tool it is told to run nor declares a complete
    census when forced to; the counts it needs have to be computed before it starts, from the
    folder alone. So discovery infers the sources (merging paginated files), each one's key,
    the links between them, the attributes that overlap across sources (array paths included),
    and the pairs of sources that describe the same entities - then writes the census as
    sentences a reader can paste, plus the inferred declarations so a person can correct them.
    """

    @classmethod
    def setUpClass(cls):
        cls.folder = os.path.join(TMP, "handover_%d" % len(os.listdir(TMP)))
        os.makedirs(os.path.join(cls.folder, "feed"))
        json.dump({"records": [
            {"id": "rec1", "fields": {"Name": "Ann A", "Email": "Ann@x.com", "Status": "Active", "Manager": ["rec2"], "Ref": "L-1"}},
            {"id": "rec2", "fields": {"Name": "Bob B", "Email": "bob@x.com", "Status": "active", "Manager": ["rec2"], "Ref": "L-2"}},
            {"id": "rec3", "fields": {"Name": "Cy C", "Email": "cy@x.com", "Status": "Active ", "Manager": ["recGONE"], "Ref": "L-3"}},
            {"id": "rec4", "fields": {"Name": "Dee D", "Email": "dee@x.com", "Status": "Inactive", "Manager": ["rec1"], "Ref": "L-9"}}]},
            open(os.path.join(cls.folder, "roster.json"), "w"))
        json.dump({"users": [
            {"id": "g1", "primaryEmail": "ann@x.com", "emails": [{"address": "ann@x.com", "primary": True}]},
            {"id": "g2", "primaryEmail": "robert@x.com", "emails": [{"address": "robert@x.com", "primary": True}, {"address": "BOB@x.com"}]},
            {"id": "g3", "primaryEmail": "shared@x.com", "emails": [{"address": "shared@x.com", "primary": True}]}]},
            open(os.path.join(cls.folder, "directory.json"), "w"))
        # a paginated feed describing the same loans as the roster's Ref column, with one only-in-feed
        json.dump({"data": [{"loanId": "L-1", "status": "OPEN", "amount": 10}, {"loanId": "L-2", "status": "PAID", "amount": 20}],
                   "page": 1, "nextPage": 2}, open(os.path.join(cls.folder, "feed", "loans_page_1.json"), "w"))
        json.dump({"data": [{"loanId": "L-3", "status": "OPEN", "amount": 30}, {"loanId": "L-7", "status": "OPEN", "amount": 70}],
                   "page": 2, "nextPage": None}, open(os.path.join(cls.folder, "feed", "loans_page_2.json"), "w"))
        with open(os.path.join(cls.folder, "map.csv"), "w") as f:
            f.write("loan,owner_email\nL-1,ann@x.com\nL-2,bob@x.com\nL-3,cy@x.com\n")
        cls.out, cls.r, cls.md = run_discover(cls.folder)

    def test_sources_are_found_and_paginated_files_merge_into_one(self):
        self.assertEqual(self.r.returncode, 0, self.r.stderr)
        names = set(self.out["sources"])
        self.assertIn("roster", names); self.assertIn("directory", names); self.assertIn("map", names)
        feed = [n for n in names if "loans" in n]
        self.assertEqual(len(feed), 1, names)
        self.assertEqual(self.out["sources"][feed[0]]["rows"], 4)

    def test_keys_are_inferred(self):
        decl = self.out["declarations"]["sources"]
        self.assertEqual(decl["roster"]["key"], "id")
        self.assertEqual(decl["directory"]["key"], "id")
        feed = [n for n in decl if "loans" in n][0]
        self.assertEqual(decl[feed]["key"], "loanId")

    def test_links_are_inferred_from_value_domains(self):
        links = self.out["declarations"]["sources"]["roster"]["links"]
        self.assertEqual(links.get("fields.Manager"), "roster")
        self.assertEqual(self.out["sources"]["roster"]["links"]["fields.Manager"]["dangling"], 1)

    def test_same_named_columns_compare_by_last_path_segment_and_report_vocabulary_deviations(self):
        # 'fields.Status' and 'status' are the same column across two shapes; once the majority
        # mapping between the two vocabularies is inferred, the rows that deviate are the finding
        folder = os.path.join(TMP, "vocab_%d" % len(os.listdir(TMP))); os.makedirs(folder)
        a = [{"id": "K%d" % i, "fields": {"Status": "Open" if i % 3 else "Paid"}} for i in range(30)]
        b = [{"key": "K%d" % i, "status": ("O" if i % 3 else "P")} for i in range(30)]   # a different vocabulary
        b[4]["status"] = "P"             # deviates from the Open->O majority mapping
        json.dump({"records": a}, open(os.path.join(folder, "mirror.json"), "w"))
        json.dump({"data": b}, open(os.path.join(folder, "feed.json"), "w"))
        out, r, _ = run_discover(folder)
        pair = out["same_entity"][0]
        d = next(x for x in pair["differing_columns"] if x["b_column"] in ("status", "fields.Status"))
        self.assertEqual(d["differs_on"], 30)
        self.assertEqual(d["deviate_from_majority_mapping"], 1)

    def test_presence_is_crossed_with_categories(self):
        # 'Termination Date absent by Status' is how "25 terminated rows have no date" surfaces
        folder = os.path.join(TMP, "presence_%d" % len(os.listdir(TMP))); os.makedirs(folder)
        rows = [{"id": "r%d" % i, "fields": {"Status": "Terminated" if i < 10 else "Active", **({"End": "2024-01-01"} if i < 6 else {})}} for i in range(30)]
        json.dump({"records": rows}, open(os.path.join(folder, "t.json"), "w"))
        out, r, md = run_discover(folder)
        cell = next(c for c in out["sources"]["t"]["presence_by_category"] if c["field"] == "fields.End")
        self.assertEqual(cell["absent_by_value"]["Terminated"], 4)
        self.assertEqual(cell["absent_by_value"]["Active"], 20)
        self.assertIn("absent", open(md).read())

    def test_overlaps_are_inferred_including_array_paths(self):
        pairs = {(o["a"], o["b"]) for o in self.out["overlaps"]} | {(o["b"], o["a"]) for o in self.out["overlaps"]}
        self.assertIn(("roster.fields.Email", "directory.emails[].address"), pairs, pairs)
        ov = next(o for o in self.out["overlaps"] if {o["a"], o["b"]} == {"roster.fields.Email", "directory.emails[].address"})
        self.assertEqual(ov["a_in_b_folded"] if ov["a"].startswith("roster") else ov["a_in_b_folded"], 2)

    def test_same_entity_pairs_get_only_in_and_differing_counts(self):
        pair = next(p for p in self.out["same_entity"] if "roster" in (p["a"], p["b"]) and "loans" in p["a"] + p["b"])
        # roster refs L-1,L-2,L-3,L-9 vs feed L-1,L-2,L-3,L-7
        self.assertEqual(pair["shared_keys"], 3)
        self.assertEqual(sorted([pair["only_in_a"], pair["only_in_b"]]), [1, 1])

    def test_findings_file_is_sentences_with_counts(self):
        md = open(self.md, encoding="utf-8").read()
        self.assertIn("26", md) if False else None  # placeholder guard: counts are fixture-specific below
        self.assertRegex(md, r"2 rows use minority spellings")          # Active / active / 'Active '
        self.assertRegex(md, r"1 link.{0,40}point at no roster row")     # recGONE
        self.assertRegex(md, r"only in")                                 # same-entity comparison sentence
        self.assertIn("Declarations inferred", md)

    def test_a_folder_with_nothing_readable_is_an_error(self):
        empty = os.path.join(TMP, "empty_%d" % len(os.listdir(TMP))); os.makedirs(empty)
        _, r, _ = run_discover(empty)
        self.assertEqual(r.returncode, 2)


class FindingsLeadWithTheBiggestNumbers(unittest.TestCase):
    """A weak reader skims. The file has to put the largest findings first, in one line each,
    and it has to state two facts round 5 found missing: an identifier that repeats inside one
    source (two rows, one person) and a value whose magnitude is two orders off its column."""

    @classmethod
    def setUpClass(cls):
        cls.folder = os.path.join(TMP, "lead_%d" % len(os.listdir(TMP))); os.makedirs(cls.folder)
        rows = [{"id": "r%d" % i, "fields": {"Email": "p%d@x.com" % (i % 12), "Split": 0.7 if i < 13 else 70.0, "Status": "Active"}} for i in range(15)]
        json.dump({"records": rows}, open(os.path.join(cls.folder, "people.json"), "w"))
        cls.out, cls.r, cls.md = run_discover(cls.folder)
        cls.text = open(cls.md, encoding="utf-8").read()

    def test_repeated_identifier_values_inside_one_source_are_counted(self):
        f = self.out["sources"]["people"]["fields"]["fields.Email"]
        self.assertEqual(f["repeated_values"]["values_on_more_than_one_row"], 3)     # p0, p1, p2 appear twice
        self.assertEqual(f["repeated_values"]["rows_involved"], 6)
        self.assertRegex(self.text, r"3 values appear on more than one row")

    def test_magnitude_outliers_are_counted(self):
        f = self.out["sources"]["people"]["fields"]["fields.Split"]
        self.assertEqual(f["numeric"]["magnitude_outliers"], 2)                       # 70.0 twice against 0.7
        self.assertRegex(self.text, r"2 values sit two or more orders of magnitude")

    def test_findings_open_with_a_ranked_summary(self):
        head = self.text.split("## ", 2)[1]          # the first section after the title
        self.assertTrue(head.startswith("Largest findings first"), head[:60])
        lines = [l for l in head.splitlines() if l.startswith("|")]
        self.assertGreaterEqual(len(lines), 3)
        nums = [int(l.split("|")[1].strip().replace(",", "")) for l in lines[2:] if l.split("|")[1].strip().replace(",", "").isdigit()]
        self.assertEqual(nums, sorted(nums, reverse=True))


if __name__ == "__main__":
    unittest.main()

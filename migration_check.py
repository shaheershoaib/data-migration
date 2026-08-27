#!/usr/bin/env python3
"""migration_check - the MECHANICAL half of the data-migration discipline, executable.

Most of a migration's discipline is judgment. These checks are not: each one is a query
whose answer is a number, and each maps to a real defect class that shipped to production
looking like success. Running them is cheap; the failures they catch are not.

Deliberately CSV/stdlib-only so it runs anywhere - on an extract, in CI, against a fixture -
without a database driver or a network. Point it at real tables by exporting them first.

  migration_check.py --spec spec.json [--json]

Spec (all sections optional - only what you declare is checked; but what you DECLARE is
validated: an unknown section, contract type, or rule key is an ERROR, because a typo'd
check is a check that silently never runs while the run looks green):
{
  "source": "old.csv", "destination": "new.csv",
  "allow_empty": false,
  "key": {"source": "id", "destination": "legacy_id",
          "identity": {"source": "name", "destination": "name", "min_match_rate": 1.0}},
  "columns": {"mapped": {"src_col": "dst_col"}, "dropped": ["deliberate"], "defaulted": ["x"]},
  "reconcile": {"columns": ["amount"], "exclude": [], "normalize": ["trim", "case", "number"]},
  "coverage": {"skipped": 0, "deferred": 0},
  "grain": {"source_parent": "customer_id", "destination_parent": "customer_id"},
  "contract": {"dst_col": {"type": "int|number|date|enum", "values": [...],
                           "required": true, "min": 0, "max": 100}},
  "counterexamples": [{"name": "...", "source_when": {"is_paid": "1"},
                       "contradicted_by": {"status": ["FAILED", "REVERSED"]}}],
  "exclusivity": [{"name": "...", "key": {"source": "id", "destination": "legacy_id"},
                   "destination_column": "status", "allow_missing": 0,
                   "states": [{"name": "...", "when": {...}, "destination_value": "..."}]}],
  "provenance": [{"artifact": "map.csv", "dated": "2026-01-01", "data_extracted": "2026-06-01"}]
}

Exit codes: 0 = every declared check passed; 1 = at least one check FAILED (a block -
the transform is not proven); 2 = the spec itself is invalid.
"""
import argparse, csv, json, os, sys
from collections import Counter
from datetime import date, datetime

KNOWN_SECTIONS = {"source", "destination", "allow_empty", "key", "columns", "grain",
                  "contract", "counterexamples", "exclusivity", "provenance",
                  "reconcile", "coverage"}
KNOWN_TYPES = {"int", "number", "date", "enum"}


def read(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _num(v):
    try:
        float(v); return True
    except (TypeError, ValueError):
        return False


def _int(v):
    try:
        int(str(v).strip()); return True
    except (TypeError, ValueError):
        return False


def _date(v):
    for parse in (date.fromisoformat, datetime.fromisoformat):
        try:
            parse(str(v).strip()); return True
        except (TypeError, ValueError):
            pass
    return False


def _blank(v):
    return v is None or v == ""


def _when_match(row, when):
    """A `when` value may be a scalar (equality) or a list (membership)."""
    for k, v in when.items():
        val = row.get(k, "")
        if isinstance(v, list):
            if val not in v:
                return False
        elif val != v:
            return False
    return True


def _unknown_keys(errors, name, obj, allowed):
    bad = sorted(set(obj) - set(allowed))
    if bad:
        errors.append("%s: unknown key(s): %s (known: %s)"
                      % (name, ", ".join(bad), ", ".join(sorted(allowed))))


def validate_spec(spec):
    """A typo'd section or type is a check that silently never runs - for a blocking
    gate, the worst possible outcome, because the run still looks green. Unknown spec
    keys are an ERROR, never a comment."""
    errors = []
    unknown = sorted(set(spec) - KNOWN_SECTIONS)
    if unknown:
        errors.append("unknown spec section(s): %s (known: %s)"
                      % (", ".join(unknown), ", ".join(sorted(KNOWN_SECTIONS))))
    key = spec.get("key")
    if key is not None:
        _unknown_keys(errors, "key", key, {"source", "destination", "identity"})
        for req in ("source", "destination"):
            if req not in key:
                errors.append("key: missing %r" % req)
        if key.get("identity"):
            _unknown_keys(errors, "key.identity", key["identity"],
                          {"source", "destination", "min_match_rate"})
    if spec.get("columns") is not None:
        _unknown_keys(errors, "columns", spec["columns"], {"mapped", "dropped", "defaulted"})
    if spec.get("grain") is not None:
        _unknown_keys(errors, "grain", spec["grain"], {"source_parent", "destination_parent"})
    for col, rule in (spec.get("contract") or {}).items():
        t = rule.get("type")
        if t is not None and t not in KNOWN_TYPES:
            errors.append("contract.%s: unknown type %r (known: %s)"
                          % (col, t, ", ".join(sorted(KNOWN_TYPES))))
        _unknown_keys(errors, "contract.%s" % col, rule,
                      {"type", "values", "required", "min", "max"})
    rec = spec.get("reconcile")
    if rec is not None:
        _unknown_keys(errors, "reconcile", rec, {"columns", "exclude", "normalize"})
        bad_norm = sorted(set(rec.get("normalize") or []) - {"trim", "case", "number"})
        if bad_norm:
            errors.append("reconcile.normalize: unknown mode(s): %s" % ", ".join(bad_norm))
        if not (spec.get("key") and (spec.get("columns") or {}).get("mapped")):
            errors.append("reconcile requires 'key' and 'columns.mapped' to know which "
                          "rows and columns to compare")
    if spec.get("coverage") is not None:
        _unknown_keys(errors, "coverage", spec["coverage"], {"skipped", "deferred"})
    for i, c in enumerate(spec.get("exclusivity") or []):
        for req in ("key", "destination_column", "states"):
            if req not in c:
                errors.append("exclusivity[%d]: missing %r" % (i, req))
    return errors


def check_key_uniqueness(rows, col, check_name="key-uniqueness"):
    """A natural key that maps N:1 resolves to whichever row it hits first - silently
    picking a wrong or blank one. Uniqueness is the precondition for trusting ANY join.
    A BLANK key is a sentinel, not a key: it cannot join, and as a map key it force-maps
    every keyless row onto one arbitrary value. Run on the DESTINATION too - a
    double-applied load mints duplicate keys there while every value stays right."""
    vals = [r.get(col) for r in rows]
    blank = sum(1 for v in vals if _blank(v))
    dupes = [k for k, n in Counter(v for v in vals if not _blank(v)).items() if n > 1]
    return {"check": check_name, "column": col, "duplicate_values": len(dupes),
            "blank_key_rows": blank, "examples": sorted(dupes)[:5],
            "ok": not dupes and not blank}


def _dest_map(dst, dk, value=None):
    """Destination rows keyed by dk - EXCLUDING blank and duplicated keys, which cannot
    prove anything: resolving them last-seen-wins is the exact trap the key step warns
    about. Returns (map, set_of_ambiguous_keys)."""
    counts = Counter(r.get(dk) for r in dst if not _blank(r.get(dk)))
    ambiguous = {k for k, n in counts.items() if n > 1}
    dmap = {}
    for r in dst:
        k = r.get(dk)
        if not _blank(k) and k not in ambiguous:
            dmap[k] = r.get(value, "") if value else r
    return dmap, ambiguous


def check_key_identity(src, dst, key_spec):
    """An id present in both systems is not evidence it MEANS the same thing. Compare an
    INDEPENDENT human-readable attribute; a low match rate is a re-keyed migration.
    The threshold is explicit and defaults to 1.0 - a silent tolerance is how 1% of rows
    stay attached to the wrong entity."""
    sk, dk = key_spec["source"], key_spec["destination"]
    ident = key_spec.get("identity")
    if not ident:
        return None
    si, di = ident["source"], ident["destination"]
    threshold = float(ident.get("min_match_rate", 1.0))
    dmap, ambiguous = _dest_map(dst, dk, value=di)
    compared = matched = missing = excluded = blank_src = 0
    mismatches = []
    for r in src:
        k = r.get(sk)
        if _blank(k):
            blank_src += 1
            continue
        if k in ambiguous:
            excluded += 1  # a duplicated destination key proves nothing either way
            continue
        if k not in dmap:
            missing += 1
            continue
        compared += 1
        if (r.get(si) or "").strip().lower() == (dmap[k] or "").strip().lower():
            matched += 1
        elif len(mismatches) < 5:
            mismatches.append({"key": k, "source": r.get(si), "destination": dmap[k]})
    rate = (matched / compared) if compared else 0.0
    return {"check": "key-identity", "compared": compared, "match_rate": round(rate, 4),
            "min_match_rate": threshold, "missing_in_destination": missing,
            "ambiguous_destination_keys": len(ambiguous), "excluded_ambiguous": excluded,
            "blank_source_keys": blank_src, "mismatch_examples": mismatches,
            "ok": compared > 0 and rate >= threshold}


def check_reconciliation(src, dst, rec, key_spec, mapped):
    """Reconcile BY VALUE over the full population - step 5, executable. Row counts,
    keys, coverage and contract all pass while one mapped column's VALUES silently
    diverged; only comparing the landed value against the source, row by row, sees it.
    Destination keys that are blank or duplicated are EXCLUDED and never vouched for -
    and a comparison that covered zero rows is not a pass."""
    sk, dk = key_spec["source"], key_spec["destination"]
    include = set(rec.get("columns") or [])
    exclude = set(rec.get("exclude") or [])
    normalize = set(rec.get("normalize") or [])
    pairs = {s: d for s, d in mapped.items()
             if s != sk and s not in exclude and (not include or s in include)}
    dmap, ambiguous = _dest_map(dst, dk)

    def norm(v):
        v = "" if v is None else str(v)
        if "trim" in normalize:
            v = v.strip()
        if "case" in normalize:
            v = v.lower()
        return v

    def same(a, b):
        na, nb = norm(a), norm(b)
        if na == nb:
            return True
        return "number" in normalize and _num(na) and _num(nb) and float(na) == float(nb)

    rows_compared = missing = 0
    by_column = Counter()
    examples = []
    for r in src:
        k = r.get(sk)
        if _blank(k) or k in ambiguous:
            continue
        drow = dmap.get(k)
        if drow is None:
            missing += 1
            continue
        rows_compared += 1
        for s_col, d_col in sorted(pairs.items()):
            if not same(r.get(s_col), drow.get(d_col)):
                by_column[s_col] += 1
                if len(examples) < 5:
                    examples.append({"key": k, "column": s_col, "source": r.get(s_col),
                                     "destination": drow.get(d_col)})
    total = sum(by_column.values())
    return {"check": "value-reconciliation", "rows_compared": rows_compared,
            "columns_compared": sorted(pairs), "mismatched_values": total,
            "mismatches_by_column": dict(by_column), "missing_in_destination": missing,
            "ambiguous_destination_keys": len(ambiguous), "examples": examples,
            "ok": rows_compared > 0 and total == 0}


def check_column_coverage(src, dst, spec):
    """A row census cannot see a column that was never carried: every row moves, one field
    is silently absent, the count is perfect. Every source column must be ACCOUNTED for."""
    src_cols = set(src[0].keys()) if src else set()
    mapped = set((spec.get("mapped") or {}).keys())
    dropped = set(spec.get("dropped") or [])
    defaulted = set(spec.get("defaulted") or [])
    unaccounted = sorted(src_cols - mapped - dropped - defaulted)
    dst_cols = set(dst[0].keys()) if dst else set()
    missing_targets = sorted(v for v in (spec.get("mapped") or {}).values() if v not in dst_cols)
    return {"check": "column-coverage", "source_columns": len(src_cols),
            "unaccounted": unaccounted, "mapped_target_missing": missing_targets,
            "ok": not unaccounted and not missing_targets}


def check_coverage(src, dst, cov):
    """'Transformed + skipped + deferred must sum to the input' is a countable claim -
    declare the skips and the census stops being decorative. A shortfall nobody declared
    is the 'it ran clean over a subset' failure, exactly."""
    skipped = int(cov.get("skipped", 0) or 0)
    deferred = int(cov.get("deferred", 0) or 0)
    expected = len(src) - skipped - deferred
    return {"check": "coverage-summation", "source_rows": len(src),
            "skipped_declared": skipped, "deferred_declared": deferred,
            "expected_destination_rows": expected, "destination_rows": len(dst),
            "ok": expected == len(dst)}


def check_grain(src, dst, spec):
    """A one-to-many collapsed to one-to-one destroys information; a load applied twice
    FANS OUT instead. Both leave plausible-looking totals - compare children-per-parent
    in BOTH directions."""
    sp, dp = spec["source_parent"], spec["destination_parent"]
    s = Counter(r.get(sp, "") for r in src)
    d = Counter(r.get(dp, "") for r in dst)
    lost = [{"parent": k, "source_rows": v, "destination_rows": d.get(k, 0)}
            for k, v in s.items() if d.get(k, 0) < v]
    gained = [{"parent": k, "source_rows": s.get(k, 0), "destination_rows": v}
              for k, v in d.items() if v > s.get(k, 0)]
    return {"check": "grain", "source_max_per_parent": max(s.values()) if s else 0,
            "destination_max_per_parent": max(d.values()) if d else 0,
            "parents_losing_rows": len(lost), "parents_gaining_rows": len(gained),
            "examples": (lost + gained)[:5], "ok": not lost and not gained}


def check_contract(dst, contract):
    """Derive the contract from the DESTINATION. A store with weak enforcement - free-text
    enums, permissive parsing - accepts every one of these without an error."""
    out = []
    for col, rule in contract.items():
        vals = [r.get(col, "") for r in dst]
        present = [v for v in vals if v not in (None, "")]
        viol = []
        if rule.get("required") and len(present) != len(vals):
            viol.append({"rule": "required", "empty_rows": len(vals) - len(present)})
        if len(vals) and not present:
            viol.append({"rule": "all-null", "rows": len(vals)})
        t = rule.get("type")
        if t == "int":
            bad = [v for v in present if not _int(v)]
            if bad:
                viol.append({"rule": "int", "non_integer": len(bad), "examples": bad[:5]})
        if t == "number":
            bad = [v for v in present if not _num(v)]
            if bad:
                viol.append({"rule": "number", "non_numeric": len(bad), "examples": bad[:5]})
        if t == "date":
            bad = [v for v in present if not _date(v)]
            if bad:
                viol.append({"rule": "date", "non_date": len(bad), "examples": bad[:5]})
        if t == "enum":
            allowed = set(rule.get("values") or [])
            bad = sorted({v for v in present if v not in allowed})
            if bad:
                viol.append({"rule": "enum", "unexpected_values": bad[:5]})
        if "min" in rule:
            bad = [v for v in present if _num(v) and float(v) < rule["min"]]
            if bad:
                viol.append({"rule": "min", "below": len(bad), "examples": bad[:5]})
        if "max" in rule:
            bad = [v for v in present if _num(v) and float(v) > rule["max"]]
            if bad:
                viol.append({"rule": "max", "above": len(bad), "examples": bad[:5]})
        if viol:
            out.append({"column": col, "violations": viol})
    return {"check": "destination-contract", "columns_checked": len(contract),
            "failing_columns": out, "ok": not out}


def check_counterexamples(src, cases):
    """An inferred meaning is a HYPOTHESIS. The counterexample query is its test: rows where
    the NAME predicts one thing and the authoritative field says another. Zero supports it;
    any refute it, and the count is the blast radius."""
    out = []
    for c in cases:
        when, contra = c.get("source_when", {}), c.get("contradicted_by", {})
        hits = 0
        for r in src:
            if _when_match(r, when) and any((r.get(k, "") in vs) for k, vs in contra.items()):
                hits += 1
        out.append({"name": c.get("name", "?"), "contradicting_rows": hits, "ok": hits == 0})
    return {"check": "counterexamples", "cases": out, "ok": all(c["ok"] for c in out)}


def check_exclusivity(src, dst, cases):
    """Mutually exclusive states BOTH asserted on one row - and whether the transform
    resolved them the right way round.

    Legacy systems routinely leave contradictory flags set: a success flag written when an
    operation is SUBMITTED and never cleared when it later fails, alongside the status field
    that records the real outcome. The row then asserts two things that cannot both be true.

    Detecting the contradiction is not enough, and this is the expensive half: what matters
    is which one WINS. A transform that reads the flag rather than the authoritative status
    migrates failures as successes - a complete-looking result where the money is wrong.
    So declare the precedence (states are listed HIGHEST first) and verify the destination
    actually landed on the winner for every row.

    Source contradictions are REPORTED but do not fail - the mess is a property of the
    legacy data, not of your transform. Resolving it wrongly is what fails. An affected
    source row the destination never received is COUNTED and fails too (declare
    `allow_missing` if the skips were deliberate): the rows this check exists for are
    exactly the ones a wrong transform drops. Blank or duplicated destination keys cannot
    be verified - they are excluded and counted, never resolved last-seen-wins.
    """
    out = []
    for c in cases:
        states = c["states"]
        col = c["destination_column"]
        sk, dk = c["key"]["source"], c["key"]["destination"]
        allow_missing = int(c.get("allow_missing", 0) or 0)
        dmap, ambiguous = _dest_map(dst, dk)
        conflicts = violations = checked = missing = 0
        examples = []
        for r in src:
            matched = [s for s in states if _when_match(r, s["when"])]
            if not matched:
                continue
            if len(matched) > 1:
                conflicts += 1
            winner = matched[0]                      # list order IS the precedence
            k = r.get(sk)
            if not _blank(k) and k in ambiguous:
                continue  # unverifiable either way; counted (and failed) via ambiguous
            drow = None if _blank(k) else dmap.get(k)
            if drow is None:
                missing += 1
                continue
            checked += 1
            got = drow.get(col, "")
            if got != winner["destination_value"]:
                violations += 1
                if len(examples) < 5:
                    examples.append({"key": k, "matched": [m["name"] for m in matched],
                                     "expected": winner["destination_value"], "got": got})
        out.append({"name": c.get("name", "?"), "rows_checked": checked,
                    "source_contradictions": conflicts,
                    "precedence_violations": violations,
                    "missing_in_destination": missing, "allow_missing": allow_missing,
                    "ambiguous_destination_keys": len(ambiguous), "examples": examples,
                    "ok": violations == 0 and missing <= allow_missing and not ambiguous})
    return {"check": "exclusivity-precedence", "cases": out,
            "ok": all(c["ok"] for c in out)}


def check_provenance(entries):
    """An artifact older than the data it maps is stale by construction - it cannot know
    about anything created since. Staleness is invisible in the output. An entry missing
    either date, or carrying a non-ISO date (lexicographic comparison lies about
    '06/01/2026'), proves nothing - that is a failure, not a pass."""
    stale, invalid = [], []
    for e in entries:
        d, x = e.get("dated"), e.get("data_extracted")
        if not d or not x:
            invalid.append({"artifact": e.get("artifact", "?"),
                            "problem": "missing dated/data_extracted"})
            continue
        try:
            dd, xx = date.fromisoformat(str(d)), date.fromisoformat(str(x))
        except ValueError:
            invalid.append({"artifact": e.get("artifact", "?"),
                            "problem": "dates must be ISO YYYY-MM-DD"})
            continue
        if dd < xx:
            stale.append(e)
    return {"check": "provenance", "artifacts": len(entries), "stale": stale,
            "invalid": invalid, "ok": not stale and not invalid}


def run(spec, base="."):
    def path(p):
        return p if os.path.isabs(p) else os.path.join(base, p)
    src = read(path(spec["source"])) if spec.get("source") else []
    dst = read(path(spec["destination"])) if spec.get("destination") else []
    # an empty declared input is the classic wrong-WHERE extract: it passes every
    # downstream check by having nothing to fail on. Empty is a BLOCK unless declared.
    empty = [side for side, rows, declared in (("source", src, spec.get("source")),
                                               ("destination", dst, spec.get("destination")))
             if declared and not rows]
    census = {"check": "row-census", "source_rows": len(src), "destination_rows": len(dst),
              "ok": not empty or bool(spec.get("allow_empty"))}
    if empty:
        census["empty_inputs"] = empty
    results = [census]
    if spec.get("key"):
        results.append(check_key_uniqueness(src, spec["key"]["source"]))
        if spec.get("destination"):
            results.append(check_key_uniqueness(dst, spec["key"]["destination"],
                                                "key-uniqueness-destination"))
        ident = check_key_identity(src, dst, spec["key"])
        if ident:
            results.append(ident)
    if spec.get("reconcile") is not None:
        results.append(check_reconciliation(src, dst, spec["reconcile"], spec["key"],
                                            spec["columns"]["mapped"]))
    if spec.get("columns"):
        results.append(check_column_coverage(src, dst, spec["columns"]))
    if spec.get("coverage") is not None:
        results.append(check_coverage(src, dst, spec["coverage"]))
    if spec.get("grain"):
        results.append(check_grain(src, dst, spec["grain"]))
    if spec.get("contract"):
        results.append(check_contract(dst, spec["contract"]))
    if spec.get("counterexamples"):
        results.append(check_counterexamples(src, spec["counterexamples"]))
    if spec.get("exclusivity"):
        results.append(check_exclusivity(src, dst, spec["exclusivity"]))
    if spec.get("provenance"):
        results.append(check_provenance(spec["provenance"]))
    return results


def main():
    ap = argparse.ArgumentParser(description="mechanical migration checks")
    ap.add_argument("--spec", required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    with open(a.spec, encoding="utf-8") as f:
        spec = json.load(f)
    errors = validate_spec(spec)
    if errors:
        # a misdeclared spec is not a passing run - and not a check failure either
        for e in errors:
            print("SPEC ERROR: %s" % e, file=sys.stderr)
        sys.exit(2)
    results = run(spec, os.path.dirname(os.path.abspath(a.spec)))
    failed = [r for r in results if not r.get("ok", True)]
    if a.json:
        print(json.dumps({"results": results, "failed": len(failed)}, indent=2))
    else:
        for r in results:
            print(("FAIL  " if not r.get("ok", True) else "ok    ") + r["check"])
            if not r.get("ok", True):
                # cases-shaped checks print each FAILING case's fields, not one blob
                multi = "cases" in r
                for d in (r["cases"] if multi else [r]):
                    if multi:
                        if d.get("ok", True):
                            continue
                        print("      case: %s" % d.get("name", "?"))
                    for k, v in d.items():
                        # 0 and 0.0 are EVIDENCE (a 0.0 match rate is the whole
                        # finding); only genuinely empty values are elided
                        if k in ("check", "ok", "name") or v is None or v == "" \
                                or v == [] or v == {}:
                            continue
                        print("        %s: %s" % (k, json.dumps(v)[:160]))
        print("\n%d/%d checks failed" % (len(failed), len(results)))
    # a failing check is a BLOCK: the transform is not proven
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

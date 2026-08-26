#!/usr/bin/env python3
"""migration_check - the MECHANICAL half of the data-migration discipline, executable.

Most of a migration's discipline is judgment. These checks are not: each one is a query
whose answer is a number, and each maps to a real defect class that shipped to production
looking like success. Running them is cheap; the failures they catch are not.

Deliberately CSV/stdlib-only so it runs anywhere - on an extract, in CI, against a fixture -
without a database driver or a network. Point it at real tables by exporting them first.

  migration_check.py --spec spec.json [--json]

Spec (all sections optional - only what you declare is checked):
{
  "source": "old.csv", "destination": "new.csv",
  "key": {"source": "id", "destination": "legacy_id",
          "identity": {"source": "name", "destination": "name"}},
  "columns": {"mapped": {"src_col": "dst_col"}, "dropped": ["deliberate"], "defaulted": ["x"]},
  "grain": {"source_parent": "customer_id", "destination_parent": "customer_id"},
  "contract": {"dst_col": {"type": "int|number|date|enum", "values": [...],
                           "required": true, "min": 0}},
  "counterexamples": [{"name": "...", "source_when": {"is_paid": "1"},
                       "contradicted_by": {"status": ["FAILED", "REVERSED"]}}],
  "provenance": [{"artifact": "map.csv", "dated": "2026-01-01", "data_extracted": "2026-06-01"}]
}
"""
import argparse, csv, json, os, sys
from collections import Counter, defaultdict


def read(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _num(v):
    try:
        float(v); return True
    except (TypeError, ValueError):
        return False


def check_key_uniqueness(rows, col):
    """A natural key that maps N:1 resolves to whichever row it hits first - silently
    picking a wrong or blank one. Uniqueness is the precondition for trusting ANY join."""
    dupes = [k for k, n in Counter(r.get(col, "") for r in rows).items() if n > 1]
    return {"check": "key-uniqueness", "column": col, "duplicate_values": len(dupes),
            "examples": sorted(d for d in dupes if d)[:5],
            "ok": not dupes}


def check_key_identity(src, dst, spec):
    """An id present in both systems is not evidence it MEANS the same thing. Compare an
    INDEPENDENT human-readable attribute; a low match rate is a re-keyed migration."""
    sk, dk = spec["source"], spec["destination"]
    ident = spec.get("identity")
    if not ident:
        return None
    si, di = ident["source"], ident["destination"]
    dmap = {r.get(dk, ""): r.get(di, "") for r in dst}
    compared = matched = 0
    mismatches = []
    for r in src:
        k = r.get(sk, "")
        if k in dmap:
            compared += 1
            if (r.get(si, "") or "").strip().lower() == (dmap[k] or "").strip().lower():
                matched += 1
            elif len(mismatches) < 5:
                mismatches.append({"key": k, "source": r.get(si), "destination": dmap[k]})
    rate = (matched / compared) if compared else 0.0
    return {"check": "key-identity", "compared": compared, "match_rate": round(rate, 4),
            "mismatch_examples": mismatches, "ok": compared > 0 and rate >= 0.99}


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


def check_grain(src, dst, spec):
    """A one-to-many collapsed to one-to-one destroys information while every row count
    still reconciles. Compare children-per-parent on both sides."""
    sp, dp = spec["source_parent"], spec["destination_parent"]
    s = Counter(r.get(sp, "") for r in src)
    d = Counter(r.get(dp, "") for r in dst)
    lost = [{"parent": k, "source_rows": v, "destination_rows": d.get(k, 0)}
            for k, v in s.items() if d.get(k, 0) < v]
    return {"check": "grain", "source_max_per_parent": max(s.values()) if s else 0,
            "destination_max_per_parent": max(d.values()) if d else 0,
            "parents_losing_rows": len(lost), "examples": lost[:5], "ok": not lost}


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
        if t in ("int", "number"):
            bad = [v for v in present if not _num(v)]
            if bad:
                viol.append({"rule": t, "non_numeric": len(bad), "examples": bad[:5]})
        if t == "enum":
            allowed = set(rule.get("values") or [])
            bad = sorted({v for v in present if v not in allowed})
            if bad:
                viol.append({"rule": "enum", "unexpected_values": bad[:5]})
        if "min" in rule:
            bad = [v for v in present if _num(v) and float(v) < rule["min"]]
            if bad:
                viol.append({"rule": "min", "below": len(bad), "examples": bad[:5]})
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
            if all((r.get(k, "") == v) for k, v in when.items()) and \
               any((r.get(k, "") in vs) for k, vs in contra.items()):
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
    legacy data, not of your transform. Resolving it wrongly is what fails.
    """
    out = []
    for c in cases:
        states = c["states"]
        col = c["destination_column"]
        sk, dk = c["key"]["source"], c["key"]["destination"]
        dmap = {r.get(dk, ""): r for r in dst}
        conflicts = violations = checked = 0
        examples = []
        for r in src:
            matched = [s for s in states
                       if all(r.get(k, "") == v for k, v in s["when"].items())]
            if not matched:
                continue
            if len(matched) > 1:
                conflicts += 1
            winner = matched[0]                      # list order IS the precedence
            drow = dmap.get(r.get(sk, ""))
            if drow is None:
                continue
            checked += 1
            got = drow.get(col, "")
            if got != winner["destination_value"]:
                violations += 1
                if len(examples) < 5:
                    examples.append({"key": r.get(sk), "matched": [m["name"] for m in matched],
                                     "expected": winner["destination_value"], "got": got})
        out.append({"name": c.get("name", "?"), "rows_checked": checked,
                    "source_contradictions": conflicts,
                    "precedence_violations": violations, "examples": examples,
                    "ok": violations == 0})
    return {"check": "exclusivity-precedence", "cases": out,
            "ok": all(c["ok"] for c in out)}


def check_provenance(entries):
    """An artifact older than the data it maps is stale by construction - it cannot know
    about anything created since. Staleness is invisible in the output."""
    stale = [e for e in entries if e.get("dated", "") < e.get("data_extracted", "")]
    return {"check": "provenance", "artifacts": len(entries), "stale": stale, "ok": not stale}


def run(spec, base="."):
    def path(p):
        return p if os.path.isabs(p) else os.path.join(base, p)
    src = read(path(spec["source"])) if spec.get("source") else []
    dst = read(path(spec["destination"])) if spec.get("destination") else []
    results = [{"check": "row-census", "source_rows": len(src), "destination_rows": len(dst),
                "ok": True}]
    if spec.get("key"):
        results.append(check_key_uniqueness(src, spec["key"]["source"]))
        ident = check_key_identity(src, dst, spec["key"])
        if ident:
            results.append(ident)
    if spec.get("columns"):
        results.append(check_column_coverage(src, dst, spec["columns"]))
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
    results = run(spec, os.path.dirname(os.path.abspath(a.spec)))
    failed = [r for r in results if not r.get("ok", True)]
    if a.json:
        print(json.dumps({"results": results, "failed": len(failed)}, indent=2))
    else:
        for r in results:
            print(("FAIL  " if not r.get("ok", True) else "ok    ") + r["check"])
            if not r.get("ok", True):
                for k, v in r.items():
                    if k not in ("check", "ok") and v not in (None, [], 0, ""):
                        print("        %s: %s" % (k, json.dumps(v)[:160]))
        print("\n%d/%d checks failed" % (len(failed), len(results)))
    # a failing check is a BLOCK: the transform is not proven
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

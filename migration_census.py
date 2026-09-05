#!/usr/bin/env python3
"""Step 0 of the data-migration loop as NUMBERS: the census of a source's mess.

Every figure here is one the skill's prose already asks for. The tool exists because an agent
that has to invent the query per dataset invents it wrong - compares the wrong two sets,
forgets to fold case, never puts two sources side by side - and a weaker reader skips the
query altogether. The tool prints the numbers; the reader decides what they mean.

    python3 migration_census.py --spec census.json [--json]

Spec:
  {"sources": {"roster":  {"path": "roster.json", "records": "records", "key": "id",
                            "links": {"fields.Manager": "roster"}, "id_like": ["fields.NMLS"]},
               "directory": {"path": "users.json", "key": "id"}},
   "overlaps": [{"name": "roster email vs directory", "a": "roster.fields.Email", "b": "directory.emails[].address"}]}

Per source: rows; key uniqueness raw and folded; per field presence split into absent / null /
empty; value counts for low-cardinality fields; spellings that fold together (case, whitespace);
id-like fields with non-digit values and collisions after digit-normalisation; numeric fields
with more than two decimals; date fields with min, max and values in the future; dangling links;
and a crosstab of every flag-like field against every categorical field, because a row that says
two contradictory things shows up there without anyone having to know the columns mean.
Overlaps compare two attributes across sources, folded, with array membership (`emails[].address`).

Exit 0 always - a census is evidence, not a gate - except 2 for a spec the tool cannot follow.
Stdlib only; shares the checker's readers.
"""
import argparse, collections, csv, datetime, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from migration_check import flatten  # noqa: E402

SOURCE_KEYS = {"path", "records", "key", "links", "id_like"}
LOW_CARDINALITY, CATEGORY_MAX = 25, 12
DIGITS = re.compile(r"^\d+$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
TRUTHY, FALSY = {True, 1, "1", "true", "yes", "y"}, {False, 0, "0", "false", "no", "n"}


def fold(v):
    return str(v).strip().casefold()


def blank(v):
    return v is None or (isinstance(v, str) and v.strip() == "")


def load_docs(path, records_key=None):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jsonl", ".ndjson"):
        with open(path, encoding="utf-8-sig") as f:
            return [json.loads(line) for line in f if line.strip()]
    if ext == ".json":
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
        if isinstance(data, dict):
            if records_key:
                data = data.get(records_key, [])
            else:
                lists = [v for v in data.values() if isinstance(v, list) and v and all(isinstance(x, dict) for x in v)]
                data = lists[0] if len(lists) == 1 else [data]
        return data
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def resolve(doc, path):
    """Values at a dotted path; a segment ending in [] fans out across the array."""
    if doc is None:
        return []
    if not path:
        return [doc]
    seg, _, rest = path.partition(".")
    if seg.endswith("[]"):
        arr = doc.get(seg[:-2]) if isinstance(doc, dict) else None
        if not isinstance(arr, list):
            return []
        out = []
        for el in arr:
            out += resolve(el, rest) if rest else [el]
        return out
    nxt = doc.get(seg) if isinstance(doc, dict) else None
    if rest:
        if isinstance(nxt, list):
            out = []
            for el in nxt:
                out += resolve(el, rest)
            return out
        return resolve(nxt, rest)
    if isinstance(nxt, list):
        return nxt
    return [nxt] if nxt is not None else []


def validate(spec):
    errors = []
    srcs = spec.get("sources")
    if not isinstance(srcs, dict) or not srcs:
        return ["spec.sources must be a non-empty object keyed by source name"]
    for name, s in srcs.items():
        bad = sorted(set(s) - SOURCE_KEYS)
        if bad:
            errors.append("sources.%s: unknown key(s): %s" % (name, ", ".join(bad)))
        if "path" not in s:
            errors.append("sources.%s: missing 'path'" % name)
        elif not os.path.exists(s["path"]):
            errors.append("sources.%s: file not found: %s" % (name, s["path"]))
        for col, target in (s.get("links") or {}).items():
            if target not in srcs:
                errors.append("sources.%s.links.%s: target %r is not a declared source" % (name, col, target))
            elif not srcs[target].get("key"):
                errors.append("sources.%s.links.%s: target %r declares no key to link against" % (name, col, target))
    for i, o in enumerate(spec.get("overlaps") or []):
        bad = sorted(set(o) - {"name", "a", "b"})
        if bad:
            errors.append("overlaps[%d]: unknown key(s): %s" % (i, ", ".join(bad)))
        for side in ("a", "b"):
            ref = o.get(side, "")
            if ref.split(".", 1)[0] not in srcs or "." not in ref:
                errors.append("overlaps[%d].%s must be '<source>.<path>' with a declared source, got %r" % (i, side, ref))
    return errors


def field_census(rows, name, declared_id_like):
    n = len(rows)
    present = [r[name] for r in rows if name in r]
    out = {"present": len(present), "absent": n - len(present),
           "null": sum(1 for v in present if v is None),
           "empty": sum(1 for v in present if isinstance(v, str) and v.strip() == "")}
    values = [v for v in present if not blank(v)]
    distinct = collections.Counter(str(v) for v in values)
    out["distinct"] = len(distinct)
    if 0 < len(distinct) <= LOW_CARDINALITY:
        out["values"] = dict(distinct.most_common())
    strings = [v for v in values if isinstance(v, str)]
    if strings:
        groups = collections.defaultdict(collections.Counter)
        for v in strings:
            groups[fold(v)][v] += 1
        variants = []
        for f, spell in groups.items():
            if len(spell) > 1:
                total = sum(spell.values())
                variants.append({"folded": f, "spellings": sorted(spell), "rows_in_minority_spellings": total - max(spell.values())})
        if variants:
            out["variant_groups"] = sorted(variants, key=lambda g: -g["rows_in_minority_spellings"])
        digit_share = sum(1 for v in strings if DIGITS.match(v.strip())) / len(strings)
        if name in declared_id_like or digit_share >= 0.6:
            norm = collections.Counter(re.sub(r"\D", "", v) for v in strings)
            norm.pop("", None)
            out["id_like"] = {"non_digit": sum(1 for v in strings if not DIGITS.match(v.strip())),
                              "collisions_after_digit_normalize": sum(1 for c in norm.values() if c > 1)}
        iso_share = sum(1 for v in strings if ISO_DATE.match(v.strip())) / len(strings)
        if iso_share >= 0.6:
            parsed, bad = [], 0
            for v in strings:
                try:
                    parsed.append(datetime.date.fromisoformat(v.strip()[:10]))
                except ValueError:
                    bad += 1
            if parsed:
                today = datetime.date.today()
                out["dates"] = {"min": parsed[0].isoformat() if len(parsed) == 1 else min(parsed).isoformat(), "max": max(parsed).isoformat(),
                                "in_future": sum(1 for d in parsed if d > today), "unparseable": bad}
    numbers = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not numbers:
        maybe = []
        for v in strings:
            try:
                maybe.append(float(v))
            except ValueError:
                maybe = []; break
        numbers = maybe if len(maybe) == len(strings) and strings else []
    if numbers:
        out["numeric"] = {"min": min(numbers), "max": max(numbers), "negative": sum(1 for x in numbers if x < 0),
                          "more_than_2_decimals": sum(1 for x in numbers if isinstance(x, float) and abs(x * 100 - round(x * 100)) > 1e-6)}
    flagvals = set(present) - {None}
    out["flag_like"] = bool(flagvals) and all((v in TRUTHY or v in FALSY or (isinstance(v, str) and v.strip().lower() in TRUTHY | FALSY)) for v in flagvals if not isinstance(v, (list, dict)))
    return out


def is_true(v):
    return v in TRUTHY or (isinstance(v, str) and v.strip().lower() in TRUTHY)


def census_source(name, s, docs, all_sources):
    rows = [flatten(d) for d in docs]
    n = len(rows)
    out = {"rows": n, "fields": {}, "links": {}, "crosstabs": []}
    keycol = s.get("key")
    if keycol:
        vals = [r.get(keycol) for r in rows]
        raw = collections.Counter(str(v) for v in vals if not blank(v))
        fld = collections.Counter(fold(v) for v in vals if not blank(v))
        out["key"] = {"column": keycol, "rows": n, "blank": sum(1 for v in vals if blank(v)),
                      "duplicates_raw": sum(1 for c in raw.values() if c > 1),
                      "duplicates_folded": sum(1 for c in fld.values() if c > 1),
                      "examples": [k for k, c in fld.items() if c > 1][:5]}
    names = []
    for r in rows:
        for k in r:
            if k not in names and not k.endswith("[]"):
                names.append(k)
    declared = set(s.get("id_like") or [])
    for k in names:
        out["fields"][k] = field_census(rows, k, declared)
    for col, target in (s.get("links") or {}).items():
        tkey = all_sources[target]["spec"].get("key")
        tkeys = {str(v) for r in all_sources[target]["rows"] for v in [r.get(tkey)] if not blank(v)}
        dangling, rows_with, total = 0, 0, 0
        for d in docs:
            ids = [v for v in resolve(d, col) if not blank(v)]
            bad = [v for v in ids if str(v) not in tkeys]
            total += len(ids); dangling += len(bad); rows_with += 1 if bad else 0
        out["links"][col] = {"target": target, "link_values": total, "dangling": dangling, "rows_with_dangling": rows_with}
    flags = [k for k, f in out["fields"].items() if f.get("flag_like") and f["present"] > 0]
    cats = [k for k, f in out["fields"].items() if not f.get("flag_like") and 2 <= f["distinct"] <= CATEGORY_MAX and "values" in f
            and all(isinstance(r.get(k), str) for r in rows if k in r and r.get(k) is not None)]
    for fk in flags:
        for ck in cats:
            if ck == fk:
                continue
            by = collections.Counter(str(r[ck]) for r in rows if ck in r and not blank(r.get(ck)) and is_true(r.get(fk)))
            if by:
                out["crosstabs"].append({"flag": fk, "category": ck, "true_by_value": dict(by.most_common())})
    return out, rows


def overlap(o, all_sources):
    def side(ref):
        src, path = ref.split(".", 1)
        raw = [str(v) for d in all_sources[src]["docs"] for v in resolve(d, path) if not blank(v) and not isinstance(v, (dict, list))]
        return set(raw), {fold(v) for v in raw}
    a_raw, a_f = side(o["a"]); b_raw, b_f = side(o["b"])
    return {"name": o.get("name", "%s vs %s" % (o["a"], o["b"])), "a": o["a"], "b": o["b"],
            "a_distinct": len(a_f), "b_distinct": len(b_f),
            "a_in_b_raw": len(a_raw & b_raw), "a_in_b_folded": len(a_f & b_f),
            "a_not_in_b": len(a_f - b_f), "b_not_in_a": len(b_f - a_f),
            "examples_a_not_in_b": sorted(a_f - b_f)[:5]}


def main():
    ap = argparse.ArgumentParser(description="census of a migration source's mess")
    ap.add_argument("--spec", required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    with open(a.spec, encoding="utf-8") as f:
        spec = json.load(f)
    errors = validate(spec)
    if errors:
        for e in errors:
            print("SPEC ERROR: %s" % e, file=sys.stderr)
        sys.exit(2)
    base = os.path.dirname(os.path.abspath(a.spec))
    srcs = {}
    for name, s in spec["sources"].items():
        path = s["path"] if os.path.isabs(s["path"]) else os.path.join(base, s["path"])
        srcs[name] = {"spec": s, "docs": load_docs(path, s.get("records"))}
        srcs[name]["rows"] = [flatten(d) for d in srcs[name]["docs"]]
    report = {"sources": {}, "overlaps": []}
    for name, s in spec["sources"].items():
        report["sources"][name], _ = census_source(name, s, srcs[name]["docs"], srcs)
    for o in spec.get("overlaps") or []:
        report["overlaps"].append(overlap(o, srcs))
    if a.json:
        print(json.dumps(report, indent=2, default=str)); return
    for name, r in report["sources"].items():
        print("== %s: %d rows" % (name, r["rows"]))
        if "key" in r:
            k = r["key"]
            print("   key %s: blank=%d duplicates_raw=%d duplicates_folded=%d %s" % (k["column"], k["blank"], k["duplicates_raw"], k["duplicates_folded"], ("e.g. " + ", ".join(k["examples"])) if k["examples"] else ""))
        for fname, f in r["fields"].items():
            line = "   %-34s present=%d absent=%d null=%d empty=%d distinct=%d" % (fname, f["present"], f["absent"], f["null"], f["empty"], f["distinct"])
            print(line)
            for g in f.get("variant_groups", [])[:6]:
                print("        variant spellings of %r: %s (%d rows in minority spellings)" % (g["folded"], g["spellings"], g["rows_in_minority_spellings"]))
            if "id_like" in f:
                print("        id-like: non_digit=%d collisions_after_digit_normalize=%d" % (f["id_like"]["non_digit"], f["id_like"]["collisions_after_digit_normalize"]))
            if "numeric" in f and (f["numeric"]["more_than_2_decimals"] or f["numeric"]["negative"]):
                print("        numeric: more_than_2_decimals=%d negative=%d min=%s max=%s" % (f["numeric"]["more_than_2_decimals"], f["numeric"]["negative"], f["numeric"]["min"], f["numeric"]["max"]))
            if "dates" in f:
                print("        dates: min=%s max=%s in_future=%d unparseable=%d" % (f["dates"]["min"], f["dates"]["max"], f["dates"]["in_future"], f["dates"]["unparseable"]))
        for col, l in r["links"].items():
            print("   link %s -> %s: values=%d dangling=%d (rows with dangling: %d)" % (col, l["target"], l["link_values"], l["dangling"], l["rows_with_dangling"]))
        for x in r["crosstabs"]:
            print("   crosstab %s=true by %s: %s" % (x["flag"], x["category"], json.dumps(x["true_by_value"])))
    for o in report["overlaps"]:
        print("== overlap %s" % o["name"])
        print("   a_distinct=%d b_distinct=%d a_in_b_raw=%d a_in_b_folded=%d a_not_in_b=%d b_not_in_a=%d %s" % (o["a_distinct"], o["b_distinct"], o["a_in_b_raw"], o["a_in_b_folded"], o["a_not_in_b"], o["b_not_in_a"], ("e.g. " + ", ".join(o["examples_a_not_in_b"])) if o["examples_a_not_in_b"] else ""))


if __name__ == "__main__":
    main()

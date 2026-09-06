#!/usr/bin/env python3
"""Step 0 of the data-migration loop as NUMBERS: the census of a source's mess.

Every figure here is one the skill's prose already asks for. The tool exists because an agent
that has to invent the query per dataset invents it wrong - compares the wrong two sets,
forgets to fold case, never puts two sources side by side - and a weaker reader skips the
query altogether. The tool prints the numbers; the reader decides what they mean.

    python3 migration_census.py --spec census.json [--json]
    python3 migration_census.py --discover <handover folder> --out findings.md [--json]

`--discover` needs NO declarations: it scans the folder for CSV / JSON / JSONL, merges paginated
files into one source, infers each source's key, the links between sources, the attributes that
overlap across sources (array paths such as `emails[].address` included) and the pairs of sources
that describe the same entities, runs the census, and writes the findings as sentences with counts
plus the declarations it inferred, so a person can correct them. It exists because the numbers have
to be right before the reader starts, whoever the reader is.

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
    if strings and _identifierish(strings):
        rep = collections.Counter(fold(v) for v in strings)
        multi = {k: c for k, c in rep.items() if c > 1}
        if multi:
            out["repeated_values"] = {"values_on_more_than_one_row": len(multi), "rows_involved": sum(multi.values()),
                                      "examples": sorted(multi)[:5]}
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
        import math
        mags = sorted(math.floor(math.log10(abs(x))) for x in numbers if x != 0)
        median_mag = mags[len(mags) // 2] if mags else 0
        out["numeric"] = {"min": min(numbers), "max": max(numbers), "negative": sum(1 for x in numbers if x < 0),
                          "more_than_2_decimals": sum(1 for x in numbers if isinstance(x, float) and abs(x * 100 - round(x * 100)) > 1e-6),
                          # a value two orders of magnitude from its column's median is a unit error
                          # (70 in a column of 0.70) far more often than a real value
                          "magnitude_outliers": sum(1 for x in numbers if x != 0 and abs(math.floor(math.log10(abs(x))) - median_mag) >= 2)}
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
    # which rows lack a field is often the finding ("terminated rows with no date"): cross the
    # ABSENCE of every partially-present field with every categorical field
    cats_for_presence = [k for k, f in out["fields"].items() if 2 <= f["distinct"] <= CATEGORY_MAX and "values" in f
                         and all(isinstance(r.get(k), str) for r in rows if k in r and r.get(k) is not None)]
    out["presence_by_category"] = []
    for fk, f in out["fields"].items():
        if not (0 < f["absent"] < n):
            continue
        for ck in cats_for_presence:
            if ck == fk:
                continue
            by = collections.Counter(str(r[ck]) for r in rows if fk not in r and ck in r and not blank(r.get(ck)))
            if by:
                out["presence_by_category"].append({"field": fk, "category": ck, "absent_by_value": dict(by.most_common())})
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


EXTS = (".csv", ".json", ".jsonl", ".ndjson")
KEYISH = re.compile(r"(^|[._ ])(id|key|[a-z]*id|[a-z]*_id|[a-z]+Id)$", re.I)
PAGE_SUFFIX = re.compile(r"[\s_\-]*(page|part|chunk|p)?[\s_\-]*\d+$", re.I)
IDLIKE = re.compile(r"^[A-Za-z]{0,6}[-_]?\d{3,}$")


def _scalars(doc, path):
    return [v for v in resolve(doc, path) if not blank(v) and not isinstance(v, (dict, list, bool))]


def _paths(doc, prefix="", depth=0):
    """Scalar paths and list-of-dict subpaths of one document, to depth 3."""
    out = []
    if not isinstance(doc, dict) or depth > 3:
        return out
    for k, v in doc.items():
        key = prefix + k
        if isinstance(v, dict):
            out += _paths(v, key + ".", depth + 1)
        elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            subs = {}
            for el in v:
                for sk, sv in el.items():
                    if not isinstance(sv, (dict, list)):
                        subs[sk] = True
            out += [key + "[]." + sk for sk in subs]
        else:
            out.append(key)
    return out


def _identifierish(values):
    """Email-like or id-like value domains are the ones worth matching across sources."""
    strs = [str(v).strip() for v in values]
    if len(strs) < 3:
        return False
    email = sum(1 for v in strs if "@" in v) / len(strs)
    idl = sum(1 for v in strs if IDLIKE.match(v) or DIGITS.match(v)) / len(strs)
    return email >= 0.6 or idl >= 0.6


def discover_sources(folder):
    """Every readable data file, paginated series merged into one source, named by stem."""
    found = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for f in sorted(files):
            if f.startswith(".") or not f.lower().endswith(EXTS):
                continue
            path = os.path.join(root, f)
            try:
                docs = load_docs(path)
            except Exception:
                continue
            if not docs or not all(isinstance(d, dict) for d in docs):
                continue
            stem = os.path.splitext(f)[0]
            base = PAGE_SUFFIX.sub("", stem) or stem
            found.append({"dir": root, "stem": stem, "base": base, "path": path, "docs": docs,
                          "fields": frozenset(k for d in docs[:50] for k in d)})
    groups = {}
    for it in found:
        groups.setdefault((it["dir"], it["base"], it["fields"]), []).append(it)
    sources = {}
    for (d, base, _), items in groups.items():
        name = base if len(items) > 1 or base == items[0]["stem"] else items[0]["stem"]
        cand, parent = name, d
        while cand in sources:                                 # disambiguate by parent directory
            parent, tail = os.path.split(parent)               # never with '.', which addresses paths
            cand = (tail + "_" + cand) if tail else cand + "_"
        docs = [doc for it in items for doc in it["docs"]]
        sources[cand] = {"paths": [os.path.relpath(it["path"], folder) for it in items], "docs": docs,
                         "rows": [flatten(doc) for doc in docs]}
    return sources


def infer_key(src):
    rows, n = src["rows"], len(src["rows"])
    cands = []
    for k in {k for r in rows for k in r if not k.endswith("[]")}:
        vals = [r.get(k) for r in rows]
        if any(blank(v) or isinstance(v, (bool, float)) for v in vals):
            continue
        if len({str(v) for v in vals}) == n:
            cands.append(k)
    if not cands:
        return None
    keyish = [k for k in cands if KEYISH.search(k)]
    pool = keyish or cands
    return sorted(pool, key=lambda k: (k.count("."), len(k)))[0]


def infer_links(sources, keys):
    """A column whose values live in another source's key domain links to it."""
    links = {}
    keysets = {n: {str(r.get(k)) for r in s["rows"] if not blank(r.get(k))}
               for n, s in sources.items() for k in [keys.get(n)] if k}
    for n, s in sources.items():
        links[n] = {}
        paths = set()
        for d in s["docs"][:200]:
            paths.update(pth for pth in _paths(d) if "[]." not in pth)
        for pth in sorted(paths):
            if pth == keys.get(n):
                continue
            allv = [str(v) for d in s["docs"] for v in _scalars(d, pth)]
            vals = set(allv)
            if len(vals) < 2:
                continue
            # a column unique within its own source is an identity, not a child link; the
            # same-entity comparison handles it (a key shared with another source)
            if len(vals) >= 0.95 * len(allv) and len(allv) >= 3:
                continue
            best = None
            for tn, tkeys in keysets.items():
                if not tkeys:
                    continue
                hits = len(vals & tkeys)
                share = hits / len(vals)
                if hits >= 2 and share >= 0.6 and (best is None or share > best[1]):
                    best = (tn, share)
            if best:
                links[n][pth] = best[0]
    return links


def infer_overlaps(sources, keys, links):
    """Identifier-ish attributes whose value domains meet across sources."""
    cands = []
    for n, s in sources.items():
        paths = set()
        for d in s["docs"][:200]:
            paths.update(_paths(d))
        for pth in sorted(paths):
            if pth in links.get(n, {}):
                continue
            vals = [v for d in s["docs"] for v in _scalars(d, pth)]
            if _identifierish(vals):
                cands.append((n, pth, {fold(v) for v in vals}))
    out = []
    for i, (an, ap, aset) in enumerate(cands):
        for bn, bp, bset in cands[i + 1:]:
            if an == bn:
                continue
            inter = len(aset & bset)
            if inter >= max(2, 0.05 * min(len(aset), len(bset))):
                out.append({"name": "%s.%s vs %s.%s" % (an, ap, bn, bp), "a": "%s.%s" % (an, ap),
                            "b": "%s.%s" % (bn, bp), "_inter": inter})
    out.sort(key=lambda o: -o["_inter"])
    for o in out:
        o.pop("_inter")
    return out[:20]


def same_entity_pairs(sources):
    """Two sources whose unique columns share most of a value domain describe the same entities:
    only-in-A, only-in-B and, for same-named columns, values that differ on shared keys."""
    uniq = {}
    for n, s in sources.items():
        rows = s["rows"]
        for k in {k for r in rows for k in r if not k.endswith("[]")}:
            vals = [str(r.get(k)).strip() for r in rows if not blank(r.get(k)) and not isinstance(r.get(k), (bool, float))]
            if len(vals) >= 3 and len(set(vals)) >= 0.95 * len(vals):
                uniq[(n, k)] = set(vals)
    out, seen = [], set()
    items = sorted(uniq.items())
    for i, ((an, ak), aset) in enumerate(items):
        for (bn, bk), bset in items[i + 1:]:
            if an == bn or (an, bn) in seen:
                continue
            shared = aset & bset
            if len(shared) < 0.5 * min(len(aset), len(bset)) or len(shared) < 3:
                continue
            seen.add((an, bn)); seen.add((bn, an))
            arow = {str(r.get(ak)).strip(): r for r in sources[an]["rows"] if not blank(r.get(ak))}
            brow = {str(r.get(bk)).strip(): r for r in sources[bn]["rows"] if not blank(r.get(bk))}
            def norm(c): return re.sub(r"[^a-z0-9]", "", c.split(".")[-1].lower())
            acols = {norm(c): c for c in {k for r in sources[an]["rows"] for k in r} if not c.endswith("[]")}
            bcols = {norm(c): c for c in {k for r in sources[bn]["rows"] for k in r} if not c.endswith("[]")}
            differing = []
            for nc in sorted(set(acols) & set(bcols)):
                ca, cb = acols[nc], bcols[nc]
                if ca == ak or cb == bk:
                    continue
                pairs = collections.Counter((fold(arow[kk].get(ca)), fold(brow[kk].get(cb))) for kk in shared)
                diff = sum(n for (x, y), n in pairs.items() if x != y)
                if diff:
                    # two vocabularies for one field map mostly one-to-one; infer the majority
                    # mapping per source value and count the rows that deviate from it - those
                    # are the real disagreements, the rest is vocabulary
                    by_a = collections.defaultdict(collections.Counter)
                    for (x, y), n in pairs.items():
                        by_a[x][y] += n
                    deviate = sum(sum(c.values()) - max(c.values()) for c in by_a.values())
                    differing.append({"a_column": ca, "b_column": cb, "differs_on": diff,
                                      "deviate_from_majority_mapping": deviate})
            differing.sort(key=lambda d: -d["differs_on"])
            out.append({"a": an, "a_key": ak, "b": bn, "b_key": bk, "shared_keys": len(shared),
                        "only_in_a": len(aset - bset), "only_in_b": len(bset - aset),
                        "differing_columns": differing[:6]})
    return out


def findings_text(report):
    """The census as sentences a reader can paste: the largest findings first in one line each,
    then everything grouped by source."""
    ranked = []   # (rows affected, where, one-line what)
    lines = []
    for name, r in report["sources"].items():
        lines.append("## %s (%d rows)" % (name, r["rows"]))
        k = r.get("key")
        if k:
            if k["blank"] or k["duplicates_folded"]:
                lines.append("- key `%s`: %d blank, %d values repeat as typed, %d repeat after folding case and space%s. One entity or two? Decide before anything joins on it."
                             % (k["column"], k["blank"], k["duplicates_raw"], k["duplicates_folded"], (" (e.g. %s)" % ", ".join(k["examples"])) if k["examples"] else ""))
                ranked.append((k["blank"] + k["duplicates_folded"], "%s.%s" % (name, k["column"]), "key blank on %d rows, %d values repeat after folding" % (k["blank"], k["duplicates_folded"])))
        else:
            lines.append("- no column is unique across all rows: nothing here can serve as a key without a rule.")
        for fname, f in r["fields"].items():
            if f["absent"] and f["present"]:
                lines.append("- `%s`: absent on %d rows, null on %d, empty on %d. Absent is not null; decide what each becomes in the destination." % (fname, f["absent"], f["null"], f["empty"]))
            vg = f.get("variant_groups", [])
            for g in vg[:8]:
                lines.append("- `%s`: %d rows use minority spellings of %r (%s). Fold before mapping and check the destination's allowed values." % (fname, g["rows_in_minority_spellings"], g["folded"], ", ".join(repr(x) for x in g["spellings"])))
            if vg:
                ranked.append((sum(g["rows_in_minority_spellings"] for g in vg), "%s.%s" % (name, fname), "%d rows use minority spellings across %d folded values" % (sum(g["rows_in_minority_spellings"] for g in vg), len(vg))))
            rv = f.get("repeated_values")
            if rv:
                lines.append("- `%s`: %d values appear on more than one row after folding (%d rows involved; e.g. %s). An identifier that repeats inside one source is two rows for one entity, or a legitimate repeat - decide which." % (fname, rv["values_on_more_than_one_row"], rv["rows_involved"], ", ".join(rv["examples"])))
                ranked.append((rv["values_on_more_than_one_row"], "%s.%s" % (name, fname), "%d identifier values appear on more than one row" % rv["values_on_more_than_one_row"]))
            il = f.get("id_like")
            if il and (il["non_digit"] or il["collisions_after_digit_normalize"]):
                lines.append("- `%s`: %d values are not digits-only; %d values collide after digit-normalisation. Normalise before joining on it, and look at the collisions." % (fname, il["non_digit"], il["collisions_after_digit_normalize"]))
                if il["non_digit"]:
                    ranked.append((il["non_digit"], "%s.%s" % (name, fname), "%d id values are not digits-only" % il["non_digit"]))
            nm = f.get("numeric")
            if nm and nm["more_than_2_decimals"]:
                lines.append("- `%s`: %d values carry more than 2 decimals (min %s, max %s). Round with a declared rule before storing minor units; truncation loses money." % (fname, nm["more_than_2_decimals"], nm["min"], nm["max"]))
                ranked.append((nm["more_than_2_decimals"], "%s.%s" % (name, fname), "%d values carry more than 2 decimals" % nm["more_than_2_decimals"]))
            if nm and nm.get("magnitude_outliers"):
                lines.append("- `%s`: %d values sit two or more orders of magnitude from the column's median (min %s, max %s). A unit error (70 in a column of 0.70) far more often than a real value; look before converting." % (fname, nm["magnitude_outliers"], nm["min"], nm["max"]))
                ranked.append((nm["magnitude_outliers"], "%s.%s" % (name, fname), "%d values are two or more orders of magnitude off the column" % nm["magnitude_outliers"]))
            if nm and nm["negative"]:
                lines.append("- `%s`: %d negative values. Does the destination accept the sign, and does its readers' arithmetic expect it?" % (fname, nm["negative"]))
            dt = f.get("dates")
            if dt and dt["in_future"]:
                lines.append("- `%s`: %d dates are after today (max %s). Real forward dates, or a clock, zone or extract problem?" % (fname, dt["in_future"], dt["max"]))
        for col, l in r["links"].items():
            if l["dangling"]:
                lines.append("- `%s`: %d links point at no %s row (%d rows affected). Orphans: decide their disposition before load; an enforced FK aborts on them, an unenforced one dangles." % (col, l["dangling"], l["target"], l["rows_with_dangling"]))
                ranked.append((l["dangling"], "%s.%s" % (name, col), "%d links point at no %s row" % (l["dangling"], l["target"])))
        for x in r["crosstabs"]:
            lines.append("- `%s` is true across `%s` as %s. If any of these combinations cannot both be true, the row asserts two states; decide which one wins, from the code that writes them." % (x["flag"], x["category"], json.dumps(x["true_by_value"])))
            vals = x["true_by_value"]
            if len(vals) > 1:
                minority = sum(vals.values()) - max(vals.values())
                ranked.append((minority, "%s.%s x %s" % (name, x["flag"], x["category"]), "flag true on %d rows outside its dominant %s value: %s" % (minority, x["category"].split(".")[-1], json.dumps(vals))))
        for x in r.get("presence_by_category", []):
            lines.append("- `%s` is absent across `%s` as %s. If absence means something different per group (a date every terminated row should have), that is the finding." % (x["field"], x["category"], json.dumps(x["absent_by_value"])))
        lines.append("")
    if report["overlaps"]:
        lines.append("## Attributes that meet across sources")
        for o in report["overlaps"]:
            lines.append("- %s: %d values shared after folding (%d as typed), %d only in the first, %d only in the second. The typed-versus-folded gap is rows whose match depends on case or whitespace." % (o["name"], o["a_in_b_folded"], o["a_in_b_raw"], o["a_not_in_b"], o["b_not_in_a"]))
        lines.append("")
    for o in report["overlaps"]:
        if o["a_not_in_b"] or o["b_not_in_a"]:
            ranked.append((o["a_not_in_b"] + o["b_not_in_a"], o["name"], "%d only in the first, %d only in the second (%d shared after folding, %d as typed)" % (o["a_not_in_b"], o["b_not_in_a"], o["a_in_b_folded"], o["a_in_b_raw"])))
    for p in report.get("same_entity", []):
        ranked.append((p["only_in_a"] + p["only_in_b"], "%s.%s vs %s.%s" % (p["a"], p["a_key"], p["b"], p["b_key"]), "%d only in %s, %d only in %s, %d shared" % (p["only_in_a"], p["a"], p["only_in_b"], p["b"], p["shared_keys"])))
        for d in p["differing_columns"]:
            ranked.append((d["deviate_from_majority_mapping"], "%s.%s vs %s.%s" % (p["a"], d["a_column"], p["b"], d["b_column"]), "%d rows deviate from the majority vocabulary mapping (%d differ as typed)" % (d["deviate_from_majority_mapping"], d["differs_on"])))
    if report.get("same_entity"):
        lines.append("## Sources that describe the same entities")
        for p in report["same_entity"]:
            diffs = "; ".join("`%s`/`%s` differs on %d (after inferring the majority vocabulary mapping, %d rows deviate)" % (d["a_column"], d["b_column"], d["differs_on"], d["deviate_from_majority_mapping"]) for d in p["differing_columns"]) or "no same-named column differs"
            lines.append("- %s.%s and %s.%s: %d shared keys, %d only in %s, %d only in %s. On shared keys: %s. Which one is the system of record for each differing field is a decision, not a default." % (p["a"], p["a_key"], p["b"], p["b_key"], p["shared_keys"], p["only_in_a"], p["a"], p["only_in_b"], p["b"], diffs))
        lines.append("")
    lines.append("## Declarations inferred (correct these and re-run with --spec if any is wrong)")
    lines.append("```json"); lines.append(json.dumps(report["declarations"], indent=1)); lines.append("```")
    ranked = [x for x in ranked if x[0] > 0]
    ranked.sort(key=lambda x: -x[0])
    head = ["# Findings computed from the handover (no declarations)", "",
            "Every number below came from the files as they are. A finding is not a defect until a person",
            "has read it against what the code that writes and reads the column says; it is a place to look.", "",
            "## Largest findings first (rows affected; carry every line into your analysis)", "",
            "| rows | where | what |", "|---|---|---|"]
    for n, where, what in ranked[:40]:
        head.append("| %d | %s | %s |" % (n, where, what.replace("|", "/")))
    head.append("")
    return "\n".join(head + lines) + "\n"


def discover(folder):
    sources = discover_sources(folder)
    if not sources:
        return None
    keys = {n: infer_key(s) for n, s in sources.items()}
    links = infer_links(sources, keys)
    overlaps = infer_overlaps(sources, keys, links)
    spec_sources = {n: {"paths": s["paths"], **({"key": keys[n]} if keys[n] else {}), **({"links": links[n]} if links[n] else {})}
                    for n, s in sources.items()}
    all_sources = {n: {"spec": spec_sources[n], "docs": s["docs"], "rows": s["rows"]} for n, s in sources.items()}
    report = {"mode": "discover", "folder": folder, "declarations": {"sources": spec_sources, "overlaps": overlaps},
              "sources": {}, "overlaps": [], "same_entity": []}
    for n in sources:
        report["sources"][n], _ = census_source(n, spec_sources[n], sources[n]["docs"], all_sources)
    for o in overlaps:
        report["overlaps"].append(overlap(o, all_sources))
    report["same_entity"] = same_entity_pairs(sources)
    return report


def main():
    ap = argparse.ArgumentParser(description="census of a migration source's mess")
    ap.add_argument("--spec")
    ap.add_argument("--discover", metavar="FOLDER", help="infer everything from a handover folder; no spec needed")
    ap.add_argument("--out", metavar="FINDINGS_MD", help="with --discover: write the findings as markdown here")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.discover:
        if not os.path.isdir(a.discover):
            print("SPEC ERROR: --discover needs a folder, got %r" % a.discover, file=sys.stderr); sys.exit(2)
        report = discover(a.discover)
        if report is None:
            print("SPEC ERROR: no readable CSV / JSON / JSONL data files under %s" % a.discover, file=sys.stderr); sys.exit(2)
        text = findings_text(report)
        if a.out:
            with open(a.out, "w", encoding="utf-8") as f:
                f.write(text)
        if a.json:
            print(json.dumps(report, indent=2, default=str))
        elif not a.out:
            print(text)
        else:
            print("findings written to %s (%d sources, %d overlaps, %d same-entity pairs)"
                  % (a.out, len(report["sources"]), len(report["overlaps"]), len(report["same_entity"])))
        return
    if not a.spec:
        print("SPEC ERROR: give --spec census.json or --discover FOLDER", file=sys.stderr); sys.exit(2)
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

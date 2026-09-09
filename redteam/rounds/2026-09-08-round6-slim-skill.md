# Round 6 - 2026-09-08 - does the skill's length cost the census? The slim skill

Question: with the skill, every model found fewer census classes than without it (Fable 18 and
18, Opus 17 and 18, Sonnet 14 and 16), and the weakest model got worse as the file grew during
2026-09-04. Is the length the cost, and does a shorter skill keep the decision discipline that
rounds 3 and 4 showed while giving the census back?

Method: SKILL.md condensed from about 11,200 words to about 3,400 by cutting the census prose
(the tool does that), the examples and the reasoning, and keeping the rules: start-here, sizing,
intake with the evidence ladder and the brief as output, reach, the decisions in step 0, the
contract, semantics from writers and readers, exclusivity, keys, fallbacks, coverage, the merge,
reconcile by value with the pre-explained-class and raw-before-folded rules, scope, scale, class,
receipt lines, the checker and its escapes. The long form moved to `references/loop-in-full.md`.
Same handover, same prompt, no pre-generated findings, three runs per condition, plus the
control that had been missing: the weakest model with no skill at all.

| condition | Haiku 4.5 (of 18) | mean | Sonnet 5 (of 18) | mean |
|---|---|---|---|---|
| no skill | 10, 6, 5 | 7.0 | 16 (one run) | 16 |
| full skill, 11,200 words | 8, 3, 6, 4, 4 | 5.0 | 14 (one run) | 14 |
| slim skill, 3,400 words | 13, 9, 11 | 11.0 | 18, 14, 14 | 15.3 |

Behaviours under the slim skill: evidence rungs recorded and judgment calls blocked rather than
defaulted in all six runs; the code request and credential pointers asked in most; the ranked
census figures carried (all three Haiku runs stated the 563 and 128 flag contradictions, the 92
third-decimal amounts, the 120 feed-only loans; two stated the 57 status deviations).

**Result 1: the length was the cost, and a real one.** On the weakest model the full skill
scored below no skill at all (5 against 7); the slim skill scores above both (11), with the
rungs and blocking intact. The long file did not add rules a weak model followed; it took
attention from the ones it might have.

**Result 2: on a mid-range model the slim skill costs nothing against the full one** (18, 14 and
14 against 14) and keeps the two-class gap to no skill that round 3 explained: the with-skill
plan spends part of the same line budget on the brief, the rungs, the ledger and the receipt,
which the census-only scorer does not count.

**Result 3: the shipped skill is the slim one.** The long form stays in the repo as the reference
behind each rule, read when a rule seems wrong for a case, not before starting. Nothing in the
decision discipline was cut; the census moved to the tool, where it runs the same for any model.

Tool-use note: the slim runs invoked the checker and the census tool from the skill directory in
most runs; one Haiku run exceeded the line cap (522 lines) and still scored highest, which says
the cap was binding the full-skill runs' census, as round 3 suspected.

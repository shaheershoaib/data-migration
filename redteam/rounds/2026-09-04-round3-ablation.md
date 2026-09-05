# Round 3 - 2026-09-04 - is the skill responsible? (ablation)

Question: rounds 1 and 2 ran strong models WITH the skill. How much of the result is the model?
Method: the round-2 handover (many sources, one target, the sources' "code" withheld), the same
prompt, with the skill instruction replaced by "use your own judgment and method; read or run
nothing outside the folder". Two strong models, each with and without the skill. Scored on the 18
planted inconsistency classes and on behaviours, the behaviours judged from the verbatim questions
each run asked, not from keyword matches.

| model | skill | planted counts found (of 18) | asked for the source's code | asked for the destination's code | credential pointers | evidence rungs recorded | judgment calls blocked, not defaulted | merge ledger with arithmetic | in-flight / freeze plan |
|---|---|---|---|---|---|---|---|---|---|
| Fable 5.1 | with | 18 | yes (the sync scenario definition) | yes (app and workflow source) | yes | yes | yes (4 blocked at rung 3) | yes | one clause |
| Fable 5.1 | without | 18 | no | no (asked only whether apps store ids) | yes | no | no (chose defaults, e.g. overrode the source's own "current plan" rule) | no | frozen snapshot + manifest |
| Opus 5 | with | 17 | yes | yes ("first - it unblocks all four") | yes | yes | yes (4 blocked at rung 3) | yes (1258 = 600 + 568 + 90) | yes |
| Opus 5 | without | 18 | no | no | no | no | partly (asked which "current" meaning; quarantined orphans) | no | no |

**Result 1: at the top end, the skill does not improve the census.** Both strong models find the
planted mess with or without it, to the exact count. Finding inconsistencies in data is what strong
models already do; the skill's claim to that is not supported for them.

**Result 2: what the skill adds at the top end is the decision discipline.** Both no-skill runs
DECIDED the ambiguous calls with a stated default and asked for confirmation afterwards; both
with-skill runs BLOCKED them with the evidence rung recorded and named what unblocks them. Neither
no-skill run asked for the source system's own logic (the sync scenario that explains the loan
mirror) or for the destination application's source; both with-skill runs made that the first
question, because the intake tells them to and the brief has a line for it. The merge ledger's
arithmetic appeared only with the skill. One example of what the difference protects against: the
no-skill run on the strongest model replaced the source's documented "current plan = not
superseded" rule with its own "latest plan effective before today" rule as a default, a money
surface, and asked for confirmation rather than treating the rule as blocked.

**Result 3: this test was the wrong one to measure the skill's core claim.** The round-2 handover's
defects are census-visible mess in the data. The skill's central claim is about defects that
reconcile clean and are still wrong (round 1: consistent mis-mappings with plausible cover stories,
10 of 10 found by a verifier WITH the skill). The ablation that matters most is that verifier
without the skill, and it has not been run yet.

**Taken together with round 2.** Weak models do not follow the skill's instructions and do not find
the mess; strong models find the mess with or without the skill and gain the asking, blocking and
receipt discipline from it. The skill's value therefore concentrates in two places: the decisions,
at every model strength; and the census, only for the middle of the range (a Sonnet-class model
scored 14 with the skill; its no-skill run is also not yet measured).

# Round 4 - 2026-09-04 - the round-1 verifier without the skill, and Sonnet without it

Two runs close the ablation. Same model as the with-skill runs, same inputs, the skill instruction
replaced by "use your own judgment and method; read or run nothing outside the folder".

## A. The round-1 verifier without the skill (the core claim)

Round 1's ten planted defects all reconcile clean per pair and carry a plausible cover story in the
transform. The with-skill verifier found 10 of 10. The no-skill verifier ALSO found 10 of 10, with
the same row counts. Finding them is not what the skill contributes.

The verdicts differ, and the verdict is what gets a defect fixed:

| defect | rows | with the skill | without the skill |
|---|---|---|---|
| D3 balance recompute filtered to active customers; 146 inactive customers owe $3,005,243.72 at balance 0 | 146 | DEST WRONG: "denormalized field disagrees with its own writer" (checked signals.py's formula verbatim) | FAITHFUL MESS: "faithful to the legacy books" because the legacy aging report also filtered archived customers |
| D1 deliverable emails dropped to NULL as a "validator fallback" | 87 | DEST WRONG as landed (unmarked fallback) | TEAM CALL, "lossy by platform constraint" (the cover story accepted) |
| D10 dormant customers deactivated by a rule in neither codebase | 70 | DEST WRONG (rule with no code or sign-off basis) | TEAM CALL |
| D4 created_by stamped with a service account on a "resumed via app" story | 1,150 | DEST WRONG; story refuted by re-running the script | DEST WRONG, low; story called inconsistent |
| D2, D9 (a business call; an unverifiable external claim) | 106, 135 | routed to the owner | routed to the owner |
| D5, D6, D7, D8 | 9, 3, 78, 166 | DEST WRONG | DEST WRONG |

Three classes, including the largest money class in the round, were softened without the skill:
the verifier accepted the transform's pre-explanation ("faithful to legacy", "platform constraint")
where the with-skill verifier checked the explanation against the destination's own readers and
formula and called the class wrong. That is the skill's Step 5 rule - a class the transform
pre-explains is still a class to verify - doing the one thing the model did not do on its own.

## B. Sonnet without the skill (the handover census)

16 of 18 planted counts without the skill, against 14 with it. Same conclusion as Fable and Opus:
the census is the model's. Without the skill: no evidence rungs, no merge ledger, no blocked
decisions, and no request for either side's code.

## What the four rounds say together

- **Finding inconsistencies in data is model capability.** Strong models do it with or without the
  skill (18/18, 18/18, 17/18, 16/18); weak models do not do it with the skill either (3 to 8 of 18),
  and do not run the tools the skill tells them to run.
- **Ruling on what was found is where the skill acts, at every strength measured.** With the skill,
  verifiers and planners asked for both sides' code first, recorded what each decision rests on,
  blocked judgment calls instead of choosing defaults (a no-skill run on the strongest model overrode
  the source's documented "current plan" rule on a pay surface as a default), verified the
  transform's cover stories instead of accepting them (three softened verdicts above), and produced
  the merge ledger arithmetic and the receipt. Those are the failure modes the skill was distilled
  from, and they are the ones a review has to catch.
- **The claim this repo makes should therefore be the narrower one.** Not "an agent with this skill
  finds defects a strong model would miss", but "an agent with this skill rules on what it finds
  the way a careful reviewer would, asks for the evidence that settles the rest, and leaves a
  receipt a second person can check". The verdicts table above is the evidence for that claim.

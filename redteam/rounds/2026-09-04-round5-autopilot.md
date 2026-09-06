# Round 5 - 2026-09-04 - the census autopilot on the weakest model

Question: can the mechanical half be made model-independent by taking the agent out of the census
entirely? `migration_census.py --discover <folder> --out findings.md` needs no declarations: it
finds the files, merges paginated exports, infers keys, links, cross-source overlaps and same-entity
pairs, and writes the findings as sentences with counts. In the product form the harness or the
human runs it BEFORE the agent starts, and the agent is handed `findings.md`.

Method: the round-2 handover, the same prompt as every earlier Haiku run plus one sentence ("the
folder contains findings.md, produced by the census tool before you started; read it first"),
three runs per condition. Scored on the same 18 planted classes.

| condition (Haiku 4.5, same handover) | runs | planted counts found (of 18) | mean |
|---|---|---|---|
| skill only, census tool named in the file | 5 | 8, 3, 6, 4, 4 | 5.0 |
| skill, census tool forced by the prompt, agent declares the census itself | 1 | 7 | 7.0 |
| skill, findings.md pre-generated (v1: per-source detail) | 3 | 12, 10, 7 | 9.7 |
| skill, findings.md pre-generated (v2: ranked summary first, plus repeated identifiers and magnitude outliers) | 3 | 9, 10, 11 | 10.0 |
| for scale: Sonnet 5 with the skill / without | 1 / 1 | 14 / 16 | |
| for scale: Opus 5 and Fable 5.1, with or without | 4 | 17 to 18 | |

**Result 1: pre-computing the census roughly doubles what the weakest model finds (5 to 10) and
narrows its spread (v2: 9 to 11).** That is the model-independent half delivered: the numbers are
right before anyone reads them, and a weak reader carries about half of them into its analysis.

**Result 2: the ceiling is the reader, not the file.** In v2 all sixteen census-visible classes are
stated in `findings.md`, most in the ranked summary at the top. The runs still carried 9 to 11.
What they dropped was not random: the facts that need one step of arithmetic across two lines
(aliases = matched via any address minus matched via primary; a category total across variant
groups), or that sit inside a longer line (the 15 licences with no member are "only in the first"
in an overlap line; the 10 unknown officers likewise). A weak model reads the first clause of a
line and moves on. The ranked summary bought consistency (9 to 11 against 7 to 12), not a higher
ceiling.

**Result 3: what stays out of reach for the weakest model.** No run at any condition asked for
the source system's own sync logic, and the judgment calls (which system is the record, what
"current" means, whether a schema comment survives the data) were decided by default or copied
from the findings' hedged wording. Those are the half that no file supplies.

**What this means for the product.** The autopilot is the right shape for the census: run it
before the agent, hand over the file, and the agent's job at step 0 is to read, not to invent.
On a strong model it removes busywork and adds a second, independent count of everything. On a
weak model it is the difference between 5 and 10 of 18, and the receipt lines say which decisions
still need a strong reviewer. "Any agent catches everything" is not a claim this evidence
supports; "any agent starts from the right numbers, and a strong one finishes" is.

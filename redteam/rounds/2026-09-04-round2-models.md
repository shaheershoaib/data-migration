# Round 2 - 2026-09-04 - the same handover, three models

Question: how much of round 1's result was the skill, and how much was the strongest model?
Method: one handover, one prompt, only the model changed. The handover is a many-source
consolidation shaped like a real engagement (semi-relational JSON exports from a no-code
database, an external origination feed that is the system of record for one entity, a
directory export, a payments export, static config files, and a designed relational target),
with the "code" that explains the sources' semantics withheld, as a developer would hand it
over. The planted mess has 18 classes with exact counts (8 people entered twice, 26 free-form
status spellings, 5 dangling manager links, 50 malformed ids, 25 terminated rows with no date,
128 reimbursed-but-rejected expenses, 236 absent approvals, 112 category variants, 92 half-cent
amounts, 3 whole-percent splits, 15 licenses pointing at no member, 40 loans with no
origination id, 120 loans only in the feed, 57 whose status moved after the export, 10 unknown
officers, 73 email aliases, 50 unmapped payment profiles, 90 non-member directory users).
Scoring: planted counts found (exact number stated near the right words), plus whether the run
asked for the source's code, the destination's code and credential pointers.

| model | skill version | planted counts found | asked for code / credentials (of 3) | ran the census tool |
|---|---|---|---|---|
| Fable 5.1 | before the census tool | 18 / 18 | 3 | n/a (tool did not exist) |
| Sonnet 5 | before the census tool | 14 / 18 | 1 | n/a |
| Haiku 4.5 | before the census tool | 8 / 18 | 0 | n/a |
| Haiku 4.5 | census tool named in step 0 | 3 / 18 | 2 | no |
| Haiku 4.5 | census tool in a start-here block, run 1 | 6 / 18 | 2 | no |
| Haiku 4.5 | same, run 2 | 4 / 18 | 1 | no |
| Haiku 4.5 | same, run 3 | 4 / 18 | 0 | no |
| Haiku 4.5 | census tool demanded by the PROMPT, not the skill | 7 / 18 | 0 | yes (census.json + output in its work dir) |

What the weak runs got wrong is the same each time: the wrong two sets compared (980
"unmapped" payments against a true 50, because transaction rows were counted against profile
rows instead of looked up), case never folded, array fields never opened (a 405-user directory
overlap that missed every alias), two sources never put side by side (the 40 / 120 / 57 loan
divergences could not appear), and facts invented against the data (an expenses table said to
have no status column; a licensing table said to have no member key). Every one is a census
query the skill describes in prose.

**Result 1: the skill carries strong models, and the strongest most.** 18, 14 and 8 of 18 in
model order, with the same file. The judgment steps - reading a feed as the system of record,
refusing a schema comment the data contradicts, blocking a decision instead of guessing - are
where the gap opens.

**Result 2: adding a tool the skill tells the model to run did not help the weakest model,
because it never ran it.** Four runs, three of them with the instruction as the first line of
the file, and the tool was not invoked once; each run read the sentence (the transcripts show
it) and wrote its own queries instead, wrongly. The output-shape instructions did land a
little: the brief appeared as a section and the code request was asked in some runs. A
prose instruction, wherever it sits, does not make a weak model run a tool it did not think
of. Run-to-run variance (8, 3, 6, 4, 4) is also larger than any effect a single run could show.

**Result 3: when the prompt forced the tool, the weakest model ran it and reached 7 of 18 -
above its unforced runs (3 to 8, mean 5) and still far below the stronger models.** The tool
prints numbers only for the declarations the model writes, and the weak model declared an
incomplete census (no overlap between the payments export and the profile map, so it reported
the map as missing although the file was in the folder), then misread parts of the output (304
legitimate repeats of a licensing key read as collisions). It also asked for no code and no
credentials. The tool moves a weak model from inventing wrong queries to reading right numbers
for the questions it thought to ask; it does not supply the questions.

**What this means for a user of the skill.** The census tool is worth running; the question
is who runs it. If the model is strong, the skill's instruction is enough. If it is not, the
invocation has to come from the harness or the human - one line in the prompt, a hook, or a
first command run by hand - and the skill now says so in its start-here block. Nothing in the
skill was changed to fit any source system; the tool knows CSV, JSON and JSONL and dotted
paths.

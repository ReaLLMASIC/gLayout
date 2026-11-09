# Language-model experiments

The question: given the explicit sharing interface, can a language model propose sharing plans that pass every check
and are small, within a short budget of verified proposals?  The models are run on tasks of the plan-selection study,
so they can be compared with the selection methods on the same layouts.  Numbers are in [RESULTS.md](RESULTS.md).

## Task and budget

* **Tasks**: the 28 selection tasks at twice the nominal width (sW = 2, sL in {1, 2}; list in
  `runs/model_tasks/tasks.json`, built by `python -m textbook_sharing.llm.tasks`).  A task is used only if its case is
  qualified and its unshared reference passes every check.
* **What the model sees** (and nothing else):
  1. the interface, `textbook_sharing/llm/interface_sharing.md`: fixed skeleton, what a plan of one group fixes, the
     two ways to write a plan, the legality rules, the objective;
  2. worked examples, `runs/model_tasks/examples.md`: two development circuits that are not task circuits (C01 basic
     mirror and C07 differential pair, SKY130, nominal size), each with programs and the evaluator's real reports,
     including one rejected program (`python -m textbook_sharing.llm.make_examples`);
  3. the task, `runs/model_tasks/<task>/task.md`: target netlist, the fixed groups and rows, the goal.
  No catalogue plan, no measured area of another plan and no hidden case data is shown.
* **Answer**: one Python block `plans = {group: SharingPlan(...) or axis_plan(...)}`.  It is parsed by a restricted
  AST evaluator (`llm/plan_parser.py`), never executed, then checked by `glayout.sharing.validate_plan`.
* **Budget**: at most 8 proposals per session; rejected and repeated proposals count.  A legal, new proposal is built
  and fully verified (`llm/evaluate.py`: the same `run_case` as every other layout); a repeated plan returns the earlier
  report.  The model then receives the tool report: overall status, stage results, bounding box, row and channel
  sizes, the sharing evidence measured on the drawn geometry, and error details.
* **Sessions**: 3 per task and model, so 84 per model.

## The two model arms

| arm | model | how it is called | conversation |
|---|---|---|---|
| OpenAI | `gpt-6.1-sol`, reasoning effort medium | Codex CLI 0.162.0-alpha.17.2, `codex exec` (`llm/run_codex.py`), logged in with a ChatGPT account | stateless: every proposal is a fresh call whose prompt holds the interface, the examples, the task and every earlier proposal with its report |
| Anthropic | `claude-sonnet-5-5` (model id recorded in the agent transcripts) | an agent session per task and repetition (`llm/agent_sessions.py`) | one agent conversation per session; the agent writes `p<k>_answer.md` and runs `bash submit.sh <k>`, which returns the report |

Both arms receive the same interface, examples, task text and report format.  The Codex calls run in an empty
temporary directory with the shell tool and every other tool family disabled, web search disabled, user
configuration and rules ignored, and no session files kept.  The agent sessions are restricted to their own folder by
their rules (`RULES` and `LAUNCH_TEXT` in `agent_sessions.py`, the exact texts the agents received).

### Isolation audit

* Codex: the JSONL event log of every call is checked; any item other than a message or reasoning flags the call.
  All 126 OpenAI sessions (84 main, 42 interface comparison) contain only agent messages.
* Agent sessions: every tool call in the transcripts is checked (`python -m textbook_sharing.llm.agent_sessions audit`).
  Allowed: Read/Write/Edit of a file inside the session folder and `bash submit.sh <k>` run inside it.  Of the 84
  sessions, 44 made only allowed calls; 39 also edited their own proposal files with text tools (`sed`, `python`),
  a protocol deviation that gives the agent no outside information; 2 were flagged automatically.  On manual review
  one of these was benign (`cat /dev/null`) and one had run `submit.sh` in the background and then read that
  background job's output file, which held only its own tool report.  No session read outside information, and all
  84 are included.  The first 66 sessions received launch text A, the last 18 text B, which adds one sentence (run the
  submit command in the foreground).  Per-session details: `results/analysis/agent_session_audit.json`.

## Two references

The selection catalogue is a sample of at most 64 plans per task, and a plan written directly as a `SharingPlan` can
express more than the six enumeration axes.  In 16 of the 28 tasks a model found a layout smaller than every
catalogue plan (for example two top straps with opposite pad ends on the cascode mirror).  Therefore:

* **best catalogue plan**: reference for the selection methods on all 56 tasks (they can only choose within the
  catalogue);
* **best known layout**: the smallest passing layout known for the task, from the catalogue and every model proposal
  of every arm.  Every method and model is measured against it on the 28 model tasks.

A model is counted by proposals (each costs one verification at most), a selection method by verifications.

## The interface comparison: what it measures

The same OpenAI model, settings and budget run on the 14 model tasks at sW2_sL1 with a second interface,
`interface_base.md`, which offers only what base gLayout expresses for a group of transistors: multi-finger devices
(fingers of one transistor share diffusion) and interdigitated or common-centroid placement.  Its single call
`fet_row(arrangement, orientation, contact_end)` maps to an axis plan with diffusion `none`, gate `per_device` and
straps at the bottom: no cross-device diffusion node and no shared gate conductor.  With it, 41 of 42 sessions end at
the area of the unshared layout; with the sharing interface the same model saves 13.1 % on average on these tasks.

The comparison therefore measures **what an interface lets a model express**, not how well a model searches: the base
interface cannot reach the shared plans, whatever the model does.  As a capability bound, the best base-expressible
catalogue plan is on average 13.1 % above the best catalogue plan on these tasks (`results/analysis/llm_interface.json`,
`capability`).

## Running the sessions again

The model calls are not part of `scripts/run_all.sh`: they need an official model interface that is already logged in.
No credentials are read or written by these scripts.

```bash
# task packages and worked examples (evaluator side)
scripts/run_in_container.sh "python -m textbook_sharing.llm.tasks"
scripts/run_in_container.sh "python -m textbook_sharing.llm.make_examples"
scripts/run_in_container.sh "python -m textbook_sharing.llm.make_examples --interface base"
```

OpenAI model through the Codex CLI (on a machine where `codex` is logged in; the evaluator runs in the container):

```json
{"model": "gpt-6.1-sol", "model_tag": "openai_gpt-6.1-sol", "effort": "medium", "max_proposals": 8, "reps": 3,
 "parallel": 6, "interface": "sharing", "examples": "runs/model_tasks/examples.md",
 "evaluator_cmd": "scripts/run_in_container.sh 'python -m textbook_sharing.llm.evaluate {session} {k}'"}
```

```bash
python -m textbook_sharing.llm.run_codex codex_main.json
```

For the interface comparison use `"model_tag": "openai_gpt-6.1-sol_baseiface"`, `"interface": "base"`,
`"examples": "runs/model_tasks/examples_base.md"` and `"only"` with the 14 sW2_sL1 task ids.

Agent sessions (Anthropic model): prepare the folders, start one agent per folder with the launch text, then audit the
transcripts.

```bash
python -m textbook_sharing.llm.agent_sessions prepare agent_main.json   # model_tag, workspace, reps, examples, evaluator_cmd
python -m textbook_sharing.llm.agent_sessions launch <workspace>/anthropic_claude-sonnet/C08_gf180_sW2_sL1/r1
python -m textbook_sharing.llm.agent_sessions audit agent_map.json <transcript dir> agent_audit.json
```

Afterwards: `python -m textbook_sharing.analysis.models`, `analysis.interface` and `analysis.scope` (all are part of
`python -m textbook_sharing.analysis.all`).

## Records

`runs/models/<model_tag>/<task>/r<rep>/` holds `session.json` (task, case, model, interface, budget),
`p<k>_answer.md` (the model's answer), `p<k>_feedback.txt` (the report it received), `p<k>_report.json` (the full
evaluator record) and `p<k>_run/result.json` (the verified layout), `seen.json` (proposal deduplication) and, for the
Codex arm, `session_done.json` (per-call token usage, item kinds and the isolation flag).  The prompts of the Codex
calls are not stored: each is the concatenation described above and can be rebuilt from these files.  The raw Codex
event logs and the agent transcripts are not part of the repository.

Budget: a call budget was estimated and written into the run configuration before any session ran; the sessions used
existing logged-in accounts, with no purchase and no new key.  Token usage: `usage` per session in
`results/analysis/llm_summary.json` (OpenAI) and `token_usage_sum` in `results/analysis/agent_session_audit.json`
(Anthropic).

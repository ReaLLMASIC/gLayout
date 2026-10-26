# Protocol amendments

Each amendment was approved before any affected dispatch and adds a declared, separately recorded procedure. No frozen manifest, bound source, budget, task identity, hidden configuration or recorded trial is modified. New cohorts use Claude Opus 5.5 as the policy, through its command-line client with all tools disabled.

## A1. Policy cohorts E1-C and E3-C (Claude Opus 5.5)

- The 24 tasks, anchors, eight visible and sixteen hidden configurations, references, benches, specifications, budgets, selection rules and analysis scripts are the same as for the GPT-6.1 cohorts. The budgets are: E1 1,200 s, 10 decisions and 3 full evaluations; E3 4 h, 24 decisions, 8 patches and 8 full evaluations; 16,384-token context and 1,024 output tokens.
- Only `model_config` (backend `claude_cli`, fresh session per decision) and the adapter implementation change. The cohort freeze binds the new adapter.
- Scope:
  - E1: 24 tasks × 3 levels × 2 trials = 144 episodes.
  - E3: A/R/B/C 24 tasks × 4 rules × 3 trials = 288 searches.
  - Parameter baseline P: 4 tasks × 3 trials × 2 variants = 24.
  - C signal ablations: 4 tasks × 3 trials × 2 variants = 24.

## A2. Hidden release per cohort

A cohort's hidden configurations are evaluated once, after two conditions hold:
- every declared search of that cohort is sealed;
- the E4 training data, split registry and recipe are frozen.

No hidden outcome can therefore inform the training design. Training data come only from train lineages.

## A3. Local-model evaluation at one inference trial

Each local-model slot runs one trial: 8 tasks × (T0 + T1–T4 × 3 seeds) = 104 searches. The decision budget, full-evaluation budget, selector (C) and hidden sets are the same as for the frontier policies.

## A4. E2 transient-completion pass

Some oracle candidates are unknown because a transient analysis exceeded the 90 s inner limit. Each is re-simulated once with a 4× inner limit, on the retained extracted netlist and an identical deck, and labelled `transient_completion_v1`. The finite-pool oracle is reported both under the frozen rule and under the completion pass.

## A5. Parallel oracle execution

Additional `e2_four_source.py run --method full_oracle --pool-id <pool>` processes run disjoint pools under the same frozen manifest. Per-pool reservation files created with `O_EXCL` prevent duplicate execution.

## A6. Format guidance in the Claude policy prompt (cohort E1-C2)

- **Observation.** Without format guidance, most E1-C episodes ended at the first decision: the action exceeded the 1,024-token output budget by 6 to 41 percent, because of long summaries and context-heavy patches.
- **Change.** Cohort E1-C2 adds format rules to the fixed system prompt only:
  - a one-sentence summary;
  - the whole action within 1,024 tokens;
  - strict unified diffs with exact hunk counts and three context lines.
- **Unchanged.** Tasks, hidden sets, budgets, gateway, selection rules, adapter mechanics and the 144-episode matrix.
- **Reporting.** The GPT-6.1 cohort is reported beside E1-C2 as the no-guidance condition.

## A7. Candidate-code failure list: frozen-compiler plan rejection

The trusted store accepts a generation failure as a candidate-code failure only in two cases:
- the candidate-stage console shows a listed exception at the start of a line;
- the stage ended by its declared time budget.

Anything else is unknown evidence. The list adds `glayout.sharing.spec.SharingPlanRejected`, the compiler's rejection of a device plan that cannot be contacted (for example, a unit width below the contactable minimum after a finger-count edit). It joins `textbook_sharing.assembly.engine.AssemblyError` under the same gold-control and source-snapshot conditions. Infrastructure failures (container kills, missing tools, out-of-memory) remain unclassified. The rule applies uniformly at collection, acceptance and E4 admission.

## A8. Injected-fault template set `faults_more2`

A fourth deterministic fault template set is applied to every frozen textbook parent `<domain>_rules_v1`, in the same way as `faults`, `faults_extra` and `faults_more`. It consists of six fixed text edits on the unmodified layout module. Each edit matches exactly once and gives a distinct program:
- length halved;
- finger count tripled;
- gate tied to the source net;
- row body tied to the gate net;
- port labels lowercased;
- first device dropped.

The resulting states have origin `injected` and are reported separately from natural states. Repair proposals come from the Claude Opus 5.5 span teacher through the same proposal collection and physical acceptance.

## A9. Candidate-code failure list: builtin programming errors; E4 validation plan v2

The list adds builtin errors whose cause lies in the candidate code:
- `FileExistsError` (for example, a candidate that changes `mkdir(exist_ok=True)` to `exist_ok=False`);
- `UnboundLocalError`;
- `NotImplementedError`;
- `RecursionError`;
- `ImportError` and `ModuleNotFoundError` for imports the candidate wrote.

Container kills, out-of-memory kills, trusted-stage budget overruns and other OS errors (`OSError`, `PermissionError`, `FileNotFoundError`) remain unknown. The checkpoint-validation plan pins `src/training.py`, so selection uses plan v2 (`runtime/e4_validation_preparation/e4_textbook_v1_validation_plan_v2.json`), which has the same registry, task index, budget and backend. T3/T4 start from the T1 checkpoints selected under this plan.

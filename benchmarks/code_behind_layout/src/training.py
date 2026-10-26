"""Completion-only SFT and fixed-reference DPO, plus train-only evidence admission.

No model or torch dependency is imported until numerical operations are requested.
Physical acceptance is read from the trusted execution store, never from labels in
candidate submissions. The adapter of that store is supplied by the executor.
"""
from dataclasses import dataclass
from collections.abc import Mapping
import json
import hashlib
import math
from pathlib import Path
import random
import tempfile

from src.measurement import assess, split_errors
from src.report_parsers import magic_drc_report, netgen_lvs_report, rc_netlist_inventory
from src.spice_validation import validate_analysis


def frozen_train_registry(registry):
    if registry.get("status") != "frozen" or not registry.get("lineages"):
        raise ValueError("Training requires a nonempty frozen split registry")
    errors = split_errors(registry)
    if errors:
        raise ValueError("Invalid split registry: " + ", ".join(errors))
    return {row["lineage_id"]: row for row in registry["lineages"]}


def admit_candidates(candidates, registry, trusted_outcomes):
    """Validate provenance and ask the trusted executor to resolve physical evidence.

    trusted_outcomes(candidate) must independently bind candidate source, circuit
    contract, configuration/PDK and saved tool artifacts. The caller must not pass
    a candidate-controlled function or load evidence from the candidate sandbox.
    """
    assignments = frozen_train_registry(registry)
    if not candidates:
        raise ValueError("No physically verified training candidates exist")
    admitted, seen = [], set()
    for row in candidates:
        required = ("candidate_id", "initial_state_id", "parent_lineage", "split", "source_role",
                    "origin", "pdk_revision", "base_source", "visible_contract", "visible_feedback",
                    "candidate_patch", "outcomes")
        if any(key not in row for key in required):
            raise ValueError("Candidate lacks required provenance/context fields")
        if row["candidate_id"] in seen:
            raise ValueError("Duplicate candidate ID")
        seen.add(row["candidate_id"])
        assignment = assignments.get(row["parent_lineage"], {})
        if (row["split"] != "train" or assignment.get("split") != "train"
                or row["source_role"] != "formal_train"):
            raise ValueError("Nontrain/development/evaluation material cannot enter training")
        if row["origin"] not in ("natural", "injected"):
            raise ValueError("Candidate origin must remain explicit")
        if not row["base_source"] or not row["visible_contract"] or not row["pdk_revision"]:
            raise ValueError("Core source, contract and PDK revision must be present")
        if not isinstance(row["candidate_patch"], str) or not row["candidate_patch"].strip():
            raise ValueError("Candidate must contain an executable source edit")
        if not row["outcomes"] or any(item.get("role") not in ("anchor", "development") for item in row["outcomes"]):
            raise ValueError("Only train anchor/development configurations may label candidates")
        scope=row["visible_contract"].get("editable_paths") if isinstance(row["visible_contract"],dict) else None
        if (not isinstance(scope,list) or not scope or len(set(scope))!=len(scope) or
            not set(scope).issubset(assignment.get("editable_paths",[])) or
            set(row["base_source"])!=set(scope) or set(row.get("candidate_source",{}))!=set(scope)):
            raise ValueError("Initial-state source maps must exactly match its declared editable-module scope")
        bind_candidate_edit(row,scope)
        physical = trusted_outcomes(row)
        if (not isinstance(physical, dict) or physical.get("trusted_physical_evidence") is not True
                or not physical.get("anchor") or not physical.get("family")
                or physical.get("source_role") != "formal_train"):
            raise ValueError("Independent trusted physical evidence is not established")
        admitted.append({**row, "verified": physical})
    return admitted


def bind_candidate_edit(candidate, allowed_paths):
    """Apply the actual diff and compare full source snapshots before label use."""
    from src.candidate_executor import apply_source_patch
    base, result = candidate["base_source"], candidate.get("candidate_source")
    if not allowed_paths or not isinstance(base, dict) or not isinstance(result, dict):
        raise ValueError("Training needs frozen editable paths and complete base/candidate source maps")
    with tempfile.TemporaryDirectory(prefix="iscas-training-edit-") as directory:
        root = Path(directory)
        for name, content in base.items():
            path = Path(name)
            if path.is_absolute() or ".." in path.parts or not isinstance(content, str):
                raise ValueError("Base source must contain ordinary declared relative text files")
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        apply_source_patch(root, candidate["candidate_patch"], allowed_paths)
        actual = {str(path.relative_to(root)): path.read_text() for path in root.rglob("*") if path.is_file()}
        if actual != result:
            raise ValueError("Candidate patch does not produce the physically evaluated source")


class TrustedPhysicalStore:
    """Read host-owned two-container evidence; never open candidate-reported logs.

    The execution host must keep this root outside policy/candidate writable
    mounts. Files are not cryptographic attestations: the trust boundary is the
    separate trusted container and host-owned source/artifact snapshots.
    """
    def __init__(self, root, registry):
        self.root = Path(root).resolve()
        self.registry = registry
        frozen_train_registry(registry)
        self.configurations = {item["configuration_id"]: item for item in registry.get("configurations", [])}
        self.configuration_rows=list(registry.get("configurations",[]))

    def _configuration(self,candidate,configuration_id):
        task_id=candidate.get("visible_contract",{}).get("task_id")
        matches=[row for row in self.configuration_rows if row["configuration_id"]==configuration_id and
            row.get("parent_lineage")==candidate["parent_lineage"] and (task_id is None or row["contract"]["task_id"]==task_id)]
        if len(matches)!=1:raise ValueError("Configuration needs one unambiguous frozen task binding")
        return matches[0]

    @staticmethod
    def _file(root, name, allow_empty=False):
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("Evidence must use a contained relative path")
        path = root / relative
        if any((root / Path(*relative.parts[:index])).is_symlink() for index in range(1, len(relative.parts) + 1)):
            raise ValueError("Evidence paths cannot contain symlinks")
        if not path.is_file() or (path.stat().st_size == 0 and not allow_empty):
            raise ValueError("Missing/empty trusted evidence artifact: " + name)
        return path

    @classmethod
    def _inspect_execution_run(cls, run, point, expected_source):
        """Shared raw-evidence validation for formal admission and dev dry checks."""
        import re
        from src.domain_runner import inspect_point
        run=Path(run).resolve();manifest=json.loads(cls._file(run,"manifest.json").read_text())
        frozen=list(point.get("frozen_source_files",[]));pack=point.get("frozen_source_pack")
        lineage_editable=point.get("lineage_editable_paths",point.get("editable_paths",[]))
        state_editable=point.get("editable_paths",list(expected_source))
        if len(set(frozen))!=len(frozen) or set(frozen)&set(lineage_editable):
            raise ValueError("Frozen source files must be distinct and outside lineage edit modules")
        if not set(state_editable).issubset(lineage_editable):raise ValueError("Initial-state scope exceeds the frozen lineage's edit surface")
        frozen += [name for name in lineage_editable if name not in state_editable]
        if (frozen and not pack) or (pack and not frozen):raise ValueError("Frozen source capsule needs its exact file list and path")
        if not isinstance(expected_source,dict) or set(expected_source)&set(frozen) or set(expected_source)|set(frozen)!=set(manifest.get("source_files",[])):
            raise ValueError("Editable modules plus the frozen capsule must bind every actual source file")
        if point.get("editable_paths") and set(expected_source)!=set(point["editable_paths"]):
            raise ValueError("Candidate must retain complete editable module text maps")
        expected_bytes={}
        for name,content in expected_source.items():
            if cls._file(run/"source",name,allow_empty=True).read_text()!=content:
                raise ValueError("Candidate edit differs from the evaluated source snapshot")
            expected_bytes[name]=cls._file(run/"source",name,allow_empty=True).read_bytes()
        for name in frozen:
            expected=cls._file(Path(pack),name,allow_empty=True).read_bytes()
            if cls._file(run/"source",name,allow_empty=True).read_bytes()!=expected:
                raise ValueError("Candidate changed an immutable source-capsule file")
            expected_bytes[name]=expected
        if json.loads(cls._file(run,"configuration.json").read_text())!=point["parameters"]:
            raise ValueError("Evaluated configuration differs from declared parameters")
        expected_trusted=point.get("trusted_evaluator_files")
        if not expected_trusted or set(expected_trusted)!=set(manifest.get("trusted_files",[])):
            raise ValueError("Frozen independent evaluator/reference snapshot is missing")
        for name,content in expected_trusted.items():
            if cls._file(run/"trusted",name,allow_empty=True).read_text()!=content:
                raise ValueError("Physical evaluator/reference differs from its independent snapshot")
        for stage in ("candidate","trusted"):
            if stage not in manifest:
                if stage=="trusted" and manifest["status"] in ("CANDIDATE_FAILED","REJECTED_OUTPUT"):continue
                raise ValueError("Physical execution stage is missing")
            state=manifest[stage]
            if state.get("container_state",{}).get("Running") is not False:
                raise ValueError("Execution stage has no final container state")
            if json.loads(cls._file(run,stage+"_stage/invocation.json").read_text())!=state:
                raise ValueError("Host manifest and saved invocation differ")
        checked=inspect_point({"run_directory":str(run)},{**point,"frozen_source_files":frozen},expected_bytes,point["parameters"])
        if checked["execution_integrity"]!="valid" or checked["failure_class"] not in (None,"candidate"):
            raise ValueError("Unknown/incomplete/infrastructure evidence cannot label a candidate")
        if not checked["S2"] and checked["gold_control"]["status"]!="complete":
            raise ValueError("Candidate failure needs a complete same-configuration trusted gold control")
        intent_audit=None
        if checked["S1"]:
            from src.device_intent import compare_device_intent
            record=json.loads(cls._file(run,"evidence/validation.json").read_text())
            lvs=record["artifacts"]["lvs"]
            reference_name=point.get("intent_reference_path","references/"+point["configuration_id"]+".spice")
            if reference_name not in expected_trusted:
                raise ValueError("Per-device intent needs the independently frozen configuration reference")
            if lvs.get("reference",reference_name)!=reference_name:
                raise ValueError("Device audit reference differs from the frozen configuration binding")
            intent_audit=compare_device_intent(
                cls._file(run/"evidence",lvs.get("netlist","layout_lvs.spice")).read_text(),
                cls._file(run/"trusted",reference_name).read_text())
            if not intent_audit["is_clean"]:
                raise ValueError("Independent per-finger device/terminal intent mismatch; quarantine this evidence before training")
        generation_failure_exception=None
        if manifest["status"]=="CANDIDATE_FAILED":
            console=cls._file(run,"candidate_stage/console.log",allow_empty=True).read_text(errors="replace")
            # The frozen compiler exposes two custom errors: AssemblyError when a
            # candidate repeatedly builds the same named cell, and SharingPlanRejected
            # when the requested device plan cannot be contacted (for example a unit
            # width below the contactable minimum after a finger-count edit). Both are
            # real API rejections of the candidate source, under the same complete
            # gold/source checks as builtin exceptions. Amendment A9 adds builtin
            # programming errors whose cause lies in the candidate code itself:
            # FileExistsError (observed: a candidate changed mkdir(exist_ok=True) to
            # exist_ok=False), UnboundLocalError (a NameError subclass printed under its
            # own name), NotImplementedError, RecursionError, and ImportError or
            # ModuleNotFoundError for imports the candidate itself wrote. Kills, OOM
            # kills, budget overruns of the trusted stage and other OS errors stay unknown.
            intrinsic=re.search(r"(?m)^(IndentationError|TabError|SyntaxError|NameError|UnboundLocalError|AttributeError|TypeError|ValueError|KeyError|IndexError|AssertionError|ZeroDivisionError|FileExistsError|NotImplementedError|RecursionError|ImportError|ModuleNotFoundError|textbook_sharing\.assembly\.engine\.AssemblyError|glayout\.sharing\.spec\.SharingPlanRejected):",console)
            if not intrinsic and manifest["candidate"].get("status")!="TIMEOUT":
                raise ValueError("Generation failure is not established as candidate code or declared-budget failure")
            if intrinsic:generation_failure_exception=intrinsic.group(1)
        contract=point["contract"];objective=contract.get("objective",{})
        if (objective.get("direction") not in ("min", "max") or objective.get("corner_aggregation") != "worst"
                or not objective.get("id") or not objective.get("unit")):
            raise ValueError("Training contract must declare one objective and worst-corner aggregation")
        quality=None
        if checked["S2"]:
            record=json.loads(cls._file(run,"evidence/validation.json").read_text());observation=record["observation"]
            records = [observation["corners"][corner]["metrics"][objective["metric"]] for corner in contract["required_corners"]]
            if any(item.get("unit") != objective["unit"] for item in records):
                raise ValueError("Physical objective measurement has the wrong unit")
            measurements = [item["value"] for item in records]
            quality = min(measurements) if objective["direction"] == "max" else max(measurements)
        return {**checked, "configuration_id":point["configuration_id"], "objective": quality,"point_evaluation_complete":True,
                "objective_definition": objective, "run_id": manifest["run_id"],"device_intent_audit":intent_audit,
                "generation_failure_exception":generation_failure_exception}

    @classmethod
    def inspect_development_run(cls, run, point, expected_source):
        """Exercise the real admission predicate without creating formal labels."""
        manifest=json.loads(cls._file(Path(run),"manifest.json").read_text())
        if not manifest.get("phase","").startswith("development"):
            raise ValueError("This dry path is only for explicitly development execution records")
        return {**cls._inspect_execution_run(run,point,expected_source),
                "admitted_to_formal_training":False,"source_role":"development_dry_admission_only"}

    def _read_run(self, name, candidate, configuration_id, expected_source, candidate_id):
        path=self._file(self.root,name)
        if path.name=="manifest.json":run=path.parent
        elif path.name=="validation.json" and path.parent.name=="evidence":run=path.parent.parent
        else:raise ValueError("Expected host-owned executor manifest or evidence/validation.json")
        manifest=json.loads(self._file(run,"manifest.json").read_text())
        if manifest.get("phase")!="formal_train":raise ValueError("Development/self-reported evidence cannot label formal training")
        config=self._configuration(candidate,configuration_id)
        if (config.get("split")!="train" or config.get("role")!="train_development" or config.get("parent_lineage")!=candidate["parent_lineage"]):
            raise ValueError("Training configuration is absent from its frozen train lineage")
        if config["contract"]["reference_id"]!=config["reference_id"] or config["contract"]["configuration_id"]!=configuration_id:
            raise ValueError("Frozen registry contract/reference binding is inconsistent")
        expected_context={"candidate_id":candidate_id,"initial_state_id":candidate["initial_state_id"],"parent_lineage":candidate["parent_lineage"],
            "split":"train","source_role":"formal_train","pdk_revision":candidate["pdk_revision"],"configuration_id":configuration_id,"reference_id":config["reference_id"]}
        if any(manifest.get("context",{}).get(k)!=v for k,v in expected_context.items()):
            raise ValueError("Trusted source/configuration identity mismatch")
        if "trusted" in manifest:
            provenance=json.loads(self._file(run,"evidence/provenance.json").read_text())
            if (provenance.get("phase")!="formal_train" or provenance.get("producer")!="trusted_container"
                or provenance.get("run_id")!=manifest.get("run_id") or provenance.get("context")!=manifest.get("context")
                or provenance.get("candidate_container_stopped") is not True):
                raise ValueError("Trusted physical provenance is inconsistent")
        point={"configuration_id":configuration_id,"parameters":config["parameters"],"contract":config["contract"],
               "trusted_evaluator_files":config.get("trusted_evaluator_files"),"gold_control":config.get("gold_control")}
        lineage=next(row for row in self.registry["lineages"] if row["lineage_id"]==candidate["parent_lineage"])
        point.update({key:lineage.get(key) for key in ("frozen_source_pack","frozen_source_files","editable_paths") if lineage.get(key) is not None})
        point["lineage_editable_paths"]=lineage["editable_paths"]
        scope=candidate["visible_contract"].get("editable_paths")
        if not isinstance(scope,list) or not scope:raise ValueError("Initial state needs an explicit complete-module edit scope")
        point["editable_paths"]=scope
        return self._inspect_execution_run(run,point,expected_source)

    def __call__(self, candidate):
        supplied=[item["configuration_id"] for item in candidate["outcomes"]]
        if not supplied or len(set(supplied))!=len(supplied):raise ValueError("Candidate outcomes must name distinct frozen domain points")
        tasks={self._configuration(candidate,name)["contract"]["task_id"] for name in supplied}
        if len(tasks)!=1 or None in tasks:raise ValueError("Candidate outcomes must bind one frozen train task")
        task_id=next(iter(tasks))
        expected={row["configuration_id"]:row for row in self.configuration_rows if row.get("split")=="train" and
            row.get("parent_lineage")==candidate["parent_lineage"] and row.get("contract",{}).get("task_id")==task_id}
        if (set(supplied)!=set(expected) or len(expected)!=9 or
            {role:sum(row.get("domain_role")==role for row in expected.values()) for role in ("anchor","development")}!={"anchor":1,"development":8}):
            raise ValueError("Candidate must cover the exact frozen one-anchor/eight-development task domain")
        if any(item["role"]!=expected[item["configuration_id"]]["domain_role"] for item in candidate["outcomes"]):
            raise ValueError("Candidate outcome roles differ from the frozen task domain")
        anchor, family, baseline_anchor, baseline_family, evidence_ids = None, [], None, [], []
        for outcome in candidate["outcomes"]:
            config_id = outcome["configuration_id"]
            result = self._read_run(outcome["evidence_path"], candidate, config_id,
                                    candidate["candidate_source"], candidate["candidate_id"])
            baseline = self._read_run(outcome["baseline_evidence_path"], candidate, config_id,
                                      candidate["base_source"], outcome["baseline_candidate_id"])
            evidence_ids.extend([result["run_id"], baseline["run_id"]])
            if outcome["role"] == "anchor":
                if anchor is not None:
                    raise ValueError("Training candidate has more than one anchor")
                anchor = result
                baseline_anchor = baseline
            else:
                family.append({**result, "baseline_S2": baseline["S2"]})
                baseline_family.append({**baseline, "baseline_S2": baseline["S2"]})
        if anchor is None or not family or len({item["configuration_id"] for item in family}) != len(family):
            raise ValueError("Training candidate requires one anchor and distinct full development outcomes")
        return {"trusted_physical_evidence": True, "source_role": "formal_train","task_id":task_id,"complete_domain_evaluation":True,"configuration_ids":sorted(expected), "anchor": anchor,
                "family": family, "baseline": {"anchor": baseline_anchor, "family": baseline_family},
                "tool_log_ids": evidence_ids}


def state_label_rule(rows, label_rule):
    """Bind this state's direction, units and tolerances to its physical contract."""
    definitions = [item["objective_definition"] for row in rows
                   for value in (row["verified"], row["verified"]["baseline"])
                   for item in [value["anchor"]] + value["family"]]
    objective = definitions[0]
    if any(item != objective for item in definitions):
        raise ValueError("One initial state must retain the same physical objective definition")
    selected = label_rule.get("objectives", {}).get(objective["id"], {})
    if any(selected.get(key) != objective.get(key) for key in ("metric", "unit", "direction")):
        raise ValueError("Frozen objective label rule differs from the trusted physical contract")
    for key in ("quality_absolute_tolerance", "quality_relative_tolerance", "quality_minimum_relative_effect"):
        value = selected.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("Each physical objective needs finite nonnegative tie/effect tolerances")
    return {**selected, "coverage_absolute_tolerance": label_rule["coverage_absolute_tolerance"]}


def build_matched_samples(candidates, label_rule):
    """Use a common physical candidate pool; discard ambiguous labels explicitly."""
    if label_rule.get("status") != "frozen" or not label_rule.get("version"):
        raise ValueError("Training labels require a frozen machine-checkable selection rule")
    groups = {}
    for row in candidates:
        groups.setdefault(row["initial_state_id"], []).append(row)
    datasets = {key: [] for key in ("T1", "T2", "T3", "T4")}
    report = {"initial_states": len(groups), "ambiguous_sft_states": 0,
              "ambiguous_preference_pairs": 0, "point_family_conflicts": 0, "duplicate_candidates": 0}
    for state, rows in sorted(groups.items()):
        first = rows[0]
        if any((row["parent_lineage"], patch_context(row), row["origin"]) !=
               (first["parent_lineage"], patch_context(first), first["origin"]) for row in rows):
            raise ValueError("Candidates for one initial state must have identical lineage/context/origin")
        unique, patches = [], set()
        for row in rows:
            if row["candidate_patch"] in patches:
                report["duplicate_candidates"] += 1
                continue
            patches.add(row["candidate_patch"])
            unique.append(row)
        rows = unique
        comparison_rule = state_label_rule(rows, label_rule)
        common = {"initial_state_id": state, "parent_lineage": first["parent_lineage"],
                  "source_role": "formal_train", "origin": first["origin"], "context": patch_context(first),
                  "label_rule_version": label_rule["version"],
                  "objective_id": rows[0]["verified"]["anchor"]["objective_definition"]["id"]}
        winners = {}
        for method, supervision in (("T1", "point"), ("T2", "family")):
            eligible = [row for row in rows if row["verified"]["anchor"]["S2"] and
                        (supervision == "point" or all(item["S1"] for item in row["verified"]["family"])) and
                        compare_outcomes(row["verified"], row["verified"]["baseline"], supervision, comparison_rule) == 1]
            best = [row for row in eligible if all(other is row or compare_outcomes(row["verified"], other["verified"], supervision, comparison_rule) == 1 for other in eligible)]
            if len(best) == 1:
                winners[method] = best[0]
        if set(winners) == {"T1", "T2"}:
            for method, row in winners.items():
                datasets[method].append({**common, "sample_id": method + ":" + state,
                    "patch": row["candidate_patch"], "candidate_id": row["candidate_id"],
                    "trusted_evidence_ids": row["verified"]["tool_log_ids"]})
        else:
            report["ambiguous_sft_states"] += 1
        for index, left in enumerate(rows):
            for right in rows[index + 1:]:
                labels = {key: compare_outcomes(left["verified"], right["verified"], supervision, comparison_rule)
                          for key, supervision in (("T3", "point"), ("T4", "family"))}
                if 0 in labels.values():
                    report["ambiguous_preference_pairs"] += 1
                    continue
                pair_id = state + ":" + ":".join(sorted([left["candidate_id"], right["candidate_id"]]))
                report["point_family_conflicts"] += labels["T3"] != labels["T4"]
                for method, preference in labels.items():
                    chosen, rejected = (left, right) if preference == 1 else (right, left)
                    datasets[method].append({**common, "sample_id": method + ":" + pair_id,
                        "pair_id": pair_id, "chosen": chosen["candidate_patch"], "rejected": rejected["candidate_patch"],
                        "chosen_candidate_id": chosen["candidate_id"], "rejected_candidate_id": rejected["candidate_id"],
                        "preference_reason": "point_physical_objective" if method == "T3" else "family_coverage_regression_then_physical_objective",
                        "trusted_evidence_ids": sorted(set(chosen["verified"]["tool_log_ids"] + rejected["verified"]["tool_log_ids"]))})
    report["samples"] = {key: len(value) for key, value in datasets.items()}
    return datasets, report


def patch_context(row):
    """Point and Family supervision receive exactly the same visible fields."""
    return json.dumps({"base_source": row["base_source"], "visible_contract": row["visible_contract"],
                       "visible_feedback": row["visible_feedback"]}, ensure_ascii=False, sort_keys=True)


def sample_identity(row):
    """Bind a small admitted sample, avoiding rereading its costly physical bundle."""
    return hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def compare_outcomes(left, right, supervision, rule):
    """Return 1/-1 for a declared physical preference; return 0 for a near tie.

    Inputs are trusted outcome summaries for the same initial state/domain.
    Point labels never inspect family outcomes. Missing family objective values
    are not replaced by artificial penalties: the quality tiebreak is available
    only when both candidates pass the entire declared family.
    """
    if supervision not in ("point", "family") or rule.get("direction") not in ("min", "max"):
        raise ValueError("Unknown supervision/objective direction")
    if any(type(rule.get(key)) not in (int, float) or not math.isfinite(rule[key]) or rule[key] < 0
           for key in ("quality_absolute_tolerance", "coverage_absolute_tolerance")):
        raise ValueError("Physical label tolerances must be declared before data selection")
    def eligible(value):
        return value["anchor"]["S2"] is True and (supervision == "point" or all(item["S1"] for item in value["family"]))
    a, b = eligible(left), eligible(right)
    if a != b:
        return 1 if a else -1
    if not a:
        return 0
    if supervision == "family":
        x, y = left["family"], right["family"]
        if (not x or {item["configuration_id"] for item in x} != {item["configuration_id"] for item in y}
                or len(x) != len(y)):
            raise ValueError("Family preferences need the same complete configuration domain")
        first = {item["configuration_id"]: item for item in x}
        second = {item["configuration_id"]: item for item in y}
        if any(first[key]["baseline_S2"] != second[key]["baseline_S2"] for key in first):
            raise ValueError("Family preferences cannot change the baseline binding")
        coverage_delta = sum(item["S2"] for item in x) / len(x) - sum(item["S2"] for item in y) / len(y)
        if abs(coverage_delta) > rule["coverage_absolute_tolerance"]:
            return 1 if coverage_delta > 0 else -1
        regressions = [sum(item["baseline_S2"] and not item["S2"] for item in values) for values in (x, y)]
        if regressions[0] != regressions[1]:
            return 1 if regressions[0] < regressions[1] else -1
        if not all(item["S2"] for item in x + y):
            return 0
        qualities = [sum(item["objective"] for item in values) / len(values) for values in (x, y)]
    else:
        qualities = [value["anchor"]["objective"] for value in (left, right)]
    if any(not isinstance(value, (float, int)) or not math.isfinite(value) for value in qualities):
        raise ValueError("A quality label requires finite physical measurements")
    difference = qualities[0] - qualities[1]
    scale = max(abs(value) for value in qualities)
    numerical_tie = max(rule["quality_absolute_tolerance"], rule.get("quality_relative_tolerance", 0) * scale)
    minimum_effect = rule.get("quality_minimum_relative_effect", 0) * scale
    if abs(difference) <= max(numerical_tie, minimum_effect):
        return 0
    return 1 if (difference > 0) == (rule["direction"] == "max") else -1


@dataclass(frozen=True)
class EncodedPatch:
    input_ids: list
    labels: list
    prompt_tokens: int
    completion_tokens: int


def encode_patch(tokenizer, context, patch, max_length):
    """Retain the complete context and edit. Reject oversize samples, never truncate.

    Tokenization uses the backbone's actual chat template and a separate assistant
    continuation, so every source/contract token receives the ignore label -100.
    EOS belongs to the assistant completion and is supervised.
    """
    if not patch or not isinstance(patch, str):
        raise ValueError("Empty/nontext editing target")
    messages = [{"role": "system", "content": "Edit the supplied layout generator. Return only the executable unified diff."},
                {"role": "user", "content": context}]
    rendered = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True)
    # Transformers 5 returns BatchEncoding by default; earlier tokenizers return
    # the plain ID sequence. Treating BatchEncoding as a list would yield keys.
    prompt = list(rendered["input_ids"] if isinstance(rendered, Mapping) else rendered)
    if any(type(token) is not int for token in prompt):
        raise ValueError("Expected one unbatched integer token sequence from the chat template")
    completion = list(tokenizer(patch, add_special_tokens=False)["input_ids"])
    if tokenizer.eos_token_id is None:
        raise ValueError("Tokenizer has no end-of-sequence token")
    completion.append(tokenizer.eos_token_id)
    if not prompt or not completion or len(prompt) + len(completion) > max_length:
        raise ValueError("Full source/contract/edit exceeds context budget; supply a declared semantic source window")
    return EncodedPatch(prompt + completion, [-100] * len(prompt) + completion, len(prompt), len(completion))


def tensor_batch(encoded, pad_token_id, length, device):
    import torch
    if length < len(encoded.input_ids):
        raise ValueError("Padding cannot truncate an edit")
    pad = length - len(encoded.input_ids)
    return {"input_ids": torch.tensor([encoded.input_ids + [pad_token_id] * pad], device=device),
            "attention_mask": torch.tensor([[1] * len(encoded.input_ids) + [0] * pad], device=device),
            "labels": torch.tensor([encoded.labels + [-100] * pad], device=device)}


def completion_log_probabilities(logits, labels):
    """Autoregressive log p(edit|context), summed over completion tokens only.

    The returned sum is intentionally not length-normalized for DPO. Float32 CE
    is computed only at supervised positions rather than over the entire prompt.
    """
    import torch
    import torch.nn.functional as F
    if logits.shape[:2] != labels.shape:
        raise ValueError("Logit/label sequence dimensions differ")
    shifted = labels[:, 1:]
    mask = shifted.ne(-100)
    counts = mask.sum(dim=-1)
    if not bool(torch.all(counts > 0)):
        raise ValueError("Every sequence needs completion tokens after the causal shift")
    selected = logits[:, :-1, :][mask].float()
    losses = F.cross_entropy(selected, shifted[mask], reduction="none")
    batch_indices = torch.arange(labels.shape[0], device=labels.device)[:, None].expand_as(mask)[mask]
    sums = torch.zeros(labels.shape[0], dtype=losses.dtype, device=labels.device)
    return sums.scatter_add(0, batch_indices, -losses), counts


def dpo_loss(policy_chosen, policy_rejected, reference_chosen, reference_rejected, beta):
    import torch.nn.functional as F
    if beta <= 0 or not math.isfinite(beta):
        raise ValueError("DPO beta must be finite and positive")
    if reference_chosen.requires_grad or reference_rejected.requires_grad:
        raise ValueError("DPO reference probabilities must be frozen")
    advantage = (policy_chosen - reference_chosen) - (policy_rejected - reference_rejected)
    return -F.logsigmoid(beta * advantage)


def adapter_parameters(model, name):
    return [value for key, value in model.named_parameters() if "." + name + "." in key]


def select_policy_adapter(model):
    model.set_adapter("policy")
    for parameter in adapter_parameters(model, "reference"):
        parameter.requires_grad_(False)


def _autocast(batch, dtype=None):
    import torch
    device = batch["input_ids"].device.type
    selected = dtype if dtype is not None else (torch.bfloat16 if device == "cuda" else None)
    return torch.autocast(device, dtype=selected, enabled=selected is not None)


def reference_log_probabilities(model, batch, autocast_dtype=None):
    """Select a distinct immutable T1 adapter, disable dropout, then restore policy."""
    import torch
    reference = adapter_parameters(model, "reference")
    policy = adapter_parameters(model, "policy")
    if not reference or not policy or {id(p) for p in reference} & {id(p) for p in policy}:
        raise ValueError("DPO requires separate policy and frozen T1 reference adapters")
    was_training = model.training
    try:
        model.set_adapter("reference")
        for parameter in reference:
            parameter.requires_grad_(False)
        model.eval()
        with torch.no_grad(), _autocast(batch, autocast_dtype):
            outputs = model(input_ids=batch["input_ids"], attention_mask=batch["attention_mask"])
            values, _ = completion_log_probabilities(outputs.logits, batch["labels"])
        return values.detach()
    finally:
        select_policy_adapter(model)
        model.train(was_training)


def dpo_backward(model, chosen_batch, rejected_batch, beta, normalizer=1, autocast_dtype=None):
    """Backpropagate exact DPO while retaining only one policy graph at a time.

    With dropout disabled, detached forward values determine the two derivatives
    dL/dlogp. Recomputed policy forwards receive those derivatives individually.
    This is the chain rule for the original DPO objective, not a surrogate loss.
    It uses four policy and two reference forwards per pair, trading two extra
    policy forwards for the memory otherwise held by the simultaneous graphs.
    The caller owns optimizer zero/step and gradient accumulation; normalizer is
    the actual accumulated group size. CUDA policy/reference use bf16 together.
    """
    import torch
    if not isinstance(normalizer, (int, float)) or not math.isfinite(normalizer) or normalizer <= 0:
        raise ValueError("DPO accumulation normalizer must be finite and positive")
    if any(isinstance(module, torch.nn.Dropout) and module.p != 0 for module in model.modules()):
        raise ValueError("Recomputed exact DPO requires dropout=0 for policy and reference")
    batches = (chosen_batch, rejected_batch)
    reference = [reference_log_probabilities(model, batch, autocast_dtype) for batch in batches]
    select_policy_adapter(model)
    detached_policy = []
    with torch.no_grad():
        for batch in batches:
            with _autocast(batch, autocast_dtype):
                output = model(input_ids=batch["input_ids"], attention_mask=batch["attention_mask"])
                values, _ = completion_log_probabilities(output.logits, batch["labels"])
            detached_policy.append(values.detach().requires_grad_(True))
            del output, values
    objective = dpo_loss(detached_policy[0], detached_policy[1], reference[0], reference[1], beta).sum() / normalizer
    if not bool(torch.isfinite(objective)):
        raise ValueError("Nonfinite DPO objective")
    coefficients = torch.autograd.grad(objective, detached_policy)
    for batch, coefficient in zip(batches, coefficients):
        with _autocast(batch, autocast_dtype):
            output = model(input_ids=batch["input_ids"], attention_mask=batch["attention_mask"])
            values, _ = completion_log_probabilities(output.logits, batch["labels"])
        torch.autograd.backward(values, grad_tensors=coefficient.detach())
        del output, values
    return objective.detach()


def set_seed(seed):
    import numpy as np
    import torch
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def capture_rng():
    import numpy as np
    import torch
    return {"python": random.getstate(), "numpy": np.random.get_state(), "torch": torch.get_rng_state(),
            "cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None}


def restore_rng(state):
    import numpy as np
    import torch
    random.setstate(state["python"])
    np.random.set_state(state["numpy"])
    torch.set_rng_state(state["torch"])
    if state["cuda"] is not None:
        torch.cuda.set_rng_state_all(state["cuda"])


def epoch_order(sample_count, seed, epoch):
    order = list(range(sample_count))
    random.Random(seed + epoch).shuffle(order)
    return order


def validate_training_manifest(manifest, method, seed):
    if manifest.get("status") != "frozen" or manifest.get("role") != "formal_training":
        raise ValueError("Formal training requires a frozen training manifest")
    if method not in ("T1", "T2", "T3", "T4") or method not in manifest.get("methods", {}):
        raise ValueError("Unknown/unprepared training method")
    if seed not in manifest.get("seeds", []) or len(set(manifest["seeds"])) < 3:
        raise ValueError("At least three distinct actual training seeds must be declared")
    method_row = manifest["methods"][method]
    if not method_row.get("samples") or not manifest.get("trusted_evidence_manifest"):
        raise ValueError("Physically verified train-only data and evidence manifest are missing")
    if method in ("T3", "T4"):
        point = manifest["methods"].get("T1", {}).get("selected_checkpoints", {}).get(str(seed))
        own = method_row.get("starting_t1_checkpoints", {}).get(str(seed))
        other = manifest["methods"].get("T4" if method == "T3" else "T3", {}).get("starting_t1_checkpoints", {}).get(str(seed))
        if not point or own != point or other != point:
            raise ValueError("T3 and T4 must start from the same selected T1 checkpoint for this seed")
    return method_row

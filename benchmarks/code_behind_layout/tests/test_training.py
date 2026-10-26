import copy
import importlib.util
import math
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

from src.training import (admit_candidates, bind_candidate_edit, compare_outcomes, completion_log_probabilities, dpo_backward, dpo_loss, encode_patch,
                          epoch_order, frozen_train_registry, reference_log_probabilities,
                          sample_identity, state_label_rule, build_matched_samples, TrustedPhysicalStore, validate_training_manifest)

HAS_TORCH = importlib.util.find_spec("torch") is not None


class TinyTokenizer:
    eos_token_id = 1

    def apply_chat_template(self, messages, tokenize, add_generation_prompt):
        return [2, 3, 4, 5]

    def __call__(self, value, add_special_tokens):
        return {"input_ids": [6, 7]}


class TrainingGateTests(unittest.TestCase):
    def test_current_empty_draft_registry_is_rejected(self):
        with self.assertRaises(ValueError):
            frozen_train_registry({"status": "draft", "lineages": []})

    def test_development_material_cannot_become_training(self):
        registry = {"status": "frozen", "lineages": [{"lineage_id": "train", "split": "train", "topology_family": "mirror"}]}
        row = {"candidate_id": "dev", "initial_state_id": "a", "parent_lineage": "train", "split": "train",
               "source_role": "phase0", "origin": "natural", "pdk_revision": "r", "base_source": "source",
               "visible_contract": {"limit": 1}, "visible_feedback": [], "candidate_patch": "diff",
               "outcomes": [{"configuration_id": "x", "role": "anchor"}]}
        with self.assertRaises(ValueError):
            admit_candidates([row], registry, lambda value: {"trusted_physical_evidence": True})

    def test_completion_mask_and_oversize_rejection(self):
        item = encode_patch(TinyTokenizer(), "entire source and contract", "diff", 7)
        self.assertEqual(item.input_ids, [2, 3, 4, 5, 6, 7, 1])
        self.assertEqual(item.labels, [-100, -100, -100, -100, 6, 7, 1])
        self.assertEqual(item.completion_tokens, 3)
        with self.assertRaises(ValueError):
            encode_patch(TinyTokenizer(), "entire source and contract", "diff", 6)
        class MappingTokenizer(TinyTokenizer):
            def apply_chat_template(self, messages, tokenize, add_generation_prompt):
                return {"input_ids": [2, 3, 4, 5], "attention_mask": [1, 1, 1, 1]}
        self.assertEqual(encode_patch(MappingTokenizer(), "full context", "diff", 7), item)

    def test_distinct_training_seeds_and_shared_t1_required(self):
        manifest = {"status": "frozen", "role": "formal_training", "seeds": [41, 73, 109],
                    "trusted_evidence_manifest": "admitted.json", "methods": {
                        "T1": {"samples": "a", "selected_checkpoints": {"41": "/selected/T1"}},
                        "T3": {"samples": "b", "starting_t1_checkpoints": {"41": "/selected/T1"}},
                        "T4": {"samples": "c", "starting_t1_checkpoints": {"41": "/selected/T1"}}}}
        self.assertTrue(validate_training_manifest(manifest, "T3", 41))
        manifest["methods"]["T4"]["starting_t1_checkpoints"]["41"] = "/different/T1"
        with self.assertRaises(ValueError):
            validate_training_manifest(manifest, "T3", 41)
        self.assertEqual(epoch_order(20, 41, 0), epoch_order(20, 41, 0))
        self.assertNotEqual(epoch_order(20, 41, 0), epoch_order(20, 73, 0))

    def test_point_family_conflict_and_tie_are_machine_derived(self):
        rule = {"direction": "max", "quality_absolute_tolerance": 0.01, "coverage_absolute_tolerance": 0}
        left = {"anchor": {"S2": True, "objective": 10.0}, "family": [
            {"configuration_id": "a", "S1": True, "S2": True, "baseline_S2": True, "objective": 10},
            {"configuration_id": "b", "S1": True, "S2": False, "baseline_S2": True, "objective": None}]}
        right = {"anchor": {"S2": True, "objective": 9.0}, "family": [
            {"configuration_id": "a", "S1": True, "S2": True, "baseline_S2": True, "objective": 9},
            {"configuration_id": "b", "S1": True, "S2": True, "baseline_S2": True, "objective": 9}]}
        self.assertEqual(compare_outcomes(left, right, "point", rule), 1)
        self.assertEqual(compare_outcomes(left, right, "family", rule), -1)
        right["anchor"]["objective"] = 9.995
        self.assertEqual(compare_outcomes(left, right, "point", rule), 0)

    def test_candidate_edit_must_reproduce_actual_source_snapshot(self):
        row = {"base_source": {"generator.py": "width = 1\n"},
               "candidate_source": {"generator.py": "width = 2\n"},
               "candidate_patch": "--- a/generator.py\n+++ b/generator.py\n@@ -1 +1 @@\n-width = 1\n+width = 2\n"}
        bind_candidate_edit(row, ["generator.py"])
        row["candidate_source"]["generator.py"] = "width = 3\n"
        with self.assertRaises(ValueError):
            bind_candidate_edit(row, ["generator.py"])

    def test_objective_rules_keep_area_and_frequency_units_separate(self):
        def row(objective):
            outcome = {"objective_definition": objective}
            value = {"anchor": outcome, "family": [outcome]}
            return {"verified": {**value, "baseline": value}}
        area = {"id": "area", "metric": "area", "unit": "um^2", "direction": "min"}
        bandwidth = {"id": "bandwidth", "metric": "bandwidth", "unit": "Hz", "direction": "max"}
        rules = {"coverage_absolute_tolerance": 0, "objectives": {
            "area": {**area, "quality_absolute_tolerance": .01, "quality_relative_tolerance": 0,
                     "quality_minimum_relative_effect": .01},
            "bandwidth": {**bandwidth, "quality_absolute_tolerance": 1, "quality_relative_tolerance": 1e-4,
                          "quality_minimum_relative_effect": .01}}}
        self.assertEqual(state_label_rule([row(area)], rules)["direction"], "min")
        frequency_rule = state_label_rule([row(bandwidth)], rules)
        left = {"anchor": {"S2": True, "objective": 71.033e6}}
        right = {"anchor": {"S2": True, "objective": 70.975e6}}
        self.assertEqual(compare_outcomes(left, right, "point", frequency_rule), 0)
        left["anchor"]["objective"] = 73e6
        self.assertEqual(compare_outcomes(left, right, "point", frequency_rule), 1)
        with self.assertRaisesRegex(ValueError, "same physical objective"):
            state_label_rule([row(area), row(bandwidth)], rules)
        rules["objectives"]["bandwidth"]["unit"] = "MHz"
        with self.assertRaisesRegex(ValueError, "differs"):
            state_label_rule([row(bandwidth)], rules)

    def test_sft_winner_must_improve_the_actual_initial_program(self):
        objective = {"id": "area", "metric": "area", "unit": "um^2", "direction": "min"}
        def outcome(value):
            item = {"configuration_id": "dev", "S1": True, "S2": True, "baseline_S2": True,
                    "objective": value, "objective_definition": objective}
            return {"anchor": item, "family": [item]}
        candidate = {"initial_state_id": "state", "parent_lineage": "compiler", "origin": "natural",
                     "base_source": {"generator.py": "source"}, "visible_contract": {}, "visible_feedback": [],
                     "candidate_id": "worse", "candidate_patch": "real source diff", "verified": {
                         **outcome(110), "baseline": outcome(100), "tool_log_ids": ["real-run"]}}
        rule = {"status": "frozen", "version": "test", "coverage_absolute_tolerance": 0, "objectives": {
            "area": {**objective, "quality_absolute_tolerance": .01, "quality_relative_tolerance": 0,
                     "quality_minimum_relative_effect": .01}}}
        datasets, report = build_matched_samples([candidate], rule)
        self.assertEqual(report["ambiguous_sft_states"], 1)
        self.assertEqual(datasets["T1"], [])
        candidate["verified"].update(outcome(80))
        datasets, report = build_matched_samples([candidate], rule)
        self.assertEqual(len(datasets["T1"]), 1)
        self.assertEqual(len(datasets["T2"]), 1)

    def test_admitted_sample_identity_changes_with_patch(self):
        first = {"sample_id": "T1:a", "context": "full source", "patch": "accepted edit"}
        second = {**first, "patch": "different edit"}
        self.assertNotEqual(sample_identity(first), sample_identity(second))
        self.assertEqual(sample_identity(first), sample_identity(dict(reversed(list(first.items())))))

    def test_training_entry_point_rejects_current_draft_before_loading_a_model(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "must_not_create"
            result = subprocess.run([sys.executable, str(root / "scripts/train_policy.py"),
                "--manifest", str(root / "configs/training/manifest.draft.json"),
                "--method", "T1", "--seed", "41", "--output", str(output), "--validate-only"],
                text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requires a frozen training manifest", result.stderr)
            self.assertFalse(output.exists())

    def test_host_development_evidence_is_not_formal_training_evidence(self):
        registry = {"status": "frozen", "lineages": [{"lineage_id": "train", "split": "train", "topology_family": "mirror"}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "run/evidence"
            evidence.mkdir(parents=True)
            (evidence / "validation.json").write_text("{}")
            (root / "run/manifest.json").write_text(json.dumps({"run_id": "run", "phase": "development_boundary_calibration"}))
            (evidence / "provenance.json").write_text(json.dumps({"producer": "trusted_container", "run_id": "run", "phase": "development_boundary_calibration"}))
            store = TrustedPhysicalStore(root, registry)
            with self.assertRaisesRegex(ValueError, "Development/self-reported"):
                store._read_run("run/evidence/validation.json", {}, "anchor", {}, "candidate")


@unittest.skipUnless(HAS_TORCH, "CPU numerical calibration needs torch")
class TrainingNumericalTests(unittest.TestCase):
    def test_prompt_and_padding_have_no_loss_gradient(self):
        import torch
        torch.set_num_threads(2)
        logits = torch.zeros((1, 5, 8), requires_grad=True)
        labels = torch.tensor([[-100, -100, 3, 4, -100]])
        logps, counts = completion_log_probabilities(logits, labels)
        self.assertEqual(counts.tolist(), [2])
        self.assertAlmostEqual(logps.item(), -2 * math.log(8), places=5)
        (-logps.sum()).backward()
        self.assertEqual(logits.grad[0, 0].abs().sum().item(), 0)
        self.assertEqual(logits.grad[0, 3:].abs().sum().item(), 0)
        self.assertGreater(logits.grad[0, 1:3].abs().sum().item(), 0)

    def test_dpo_formula_and_fixed_reference(self):
        import torch
        chosen = torch.tensor([-2.0], requires_grad=True)
        rejected = torch.tensor([-5.0], requires_grad=True)
        ref_chosen, ref_rejected = torch.tensor([-3.0]), torch.tensor([-4.0])
        loss = dpo_loss(chosen, rejected, ref_chosen, ref_rejected, 0.1).mean()
        self.assertAlmostEqual(loss.item(), math.log1p(math.exp(-0.2)), places=6)
        loss.backward()
        self.assertLess(chosen.grad.item(), 0)
        self.assertGreater(rejected.grad.item(), 0)
        self.assertIsNone(ref_chosen.grad)
        with self.assertRaises(ValueError):
            dpo_loss(chosen, rejected, ref_chosen.requires_grad_(), ref_rejected, 0.1)

    def test_optimizer_and_rng_resume_matches_uninterrupted_cpu(self):
        import torch
        from src.training import capture_rng, restore_rng, set_seed
        set_seed(41)
        model = torch.nn.Linear(3, 2)
        optimizer = torch.optim.AdamW(model.parameters(), lr=0.01)
        def step():
            optimizer.zero_grad()
            loss = model(torch.randn(2, 3)).square().mean()
            loss.backward()
            optimizer.step()
            return loss.item()
        step()
        checkpoint = copy.deepcopy({"model": model.state_dict(), "optimizer": optimizer.state_dict(), "rng": capture_rng()})
        expected_loss = step()
        expected = copy.deepcopy(model.state_dict())
        model.load_state_dict(checkpoint["model"])
        optimizer.load_state_dict(checkpoint["optimizer"])
        restore_rng(checkpoint["rng"])
        self.assertEqual(expected_loss, step())
        for name, values in model.state_dict().items():
            self.assertTrue(torch.equal(values, expected[name]))

    @unittest.skipUnless(importlib.util.find_spec("peft") is not None, "PEFT reference-state calibration")
    def test_peft_reference_is_t1_and_remains_constant_as_policy_changes(self):
        import torch
        from peft import LoraConfig, get_peft_model, get_peft_model_state_dict, set_peft_model_state_dict
        from transformers import GPT2Config, GPT2LMHeadModel
        torch.manual_seed(41)
        model = GPT2LMHeadModel(GPT2Config(vocab_size=24, n_layer=1, n_head=2, n_embd=16,
                                           n_positions=16, bos_token_id=0, eos_token_id=1,
                                           resid_pdrop=0, embd_pdrop=0, attn_pdrop=0))
        recipe = LoraConfig(r=2, lora_alpha=4, target_modules=["c_attn"], task_type="CAUSAL_LM", lora_dropout=0)
        model = get_peft_model(model, recipe, adapter_name="policy")
        model.add_adapter("reference", recipe)
        for name, parameter in model.named_parameters():
            if ".policy." in name:
                parameter.data.normal_(std=0.1)
        set_peft_model_state_dict(model, get_peft_model_state_dict(model, adapter_name="policy"), adapter_name="reference")
        batch = {"input_ids": torch.tensor([[2, 3, 4, 5]]), "attention_mask": torch.ones(1, 4, dtype=torch.long),
                 "labels": torch.tensor([[-100, -100, 4, 5]])}
        model.train()
        first = reference_log_probabilities(model, batch)
        with torch.no_grad():
            policy_initial, _ = completion_log_probabilities(model(batch["input_ids"]).logits, batch["labels"])
        self.assertTrue(torch.equal(first, policy_initial))
        for name, parameter in model.named_parameters():
            if ".policy." in name:
                parameter.data.add_(0.2)
        second = reference_log_probabilities(model, batch)
        self.assertTrue(torch.equal(first, second))
        self.assertEqual(model.active_adapter, "policy")
        self.assertTrue(model.training)
        self.assertTrue(all(not parameter.requires_grad for name, parameter in model.named_parameters() if ".reference." in name))
        self.assertTrue(all(parameter.requires_grad for name, parameter in model.named_parameters() if ".policy." in name))

    @unittest.skipUnless(importlib.util.find_spec("peft") is not None, "PEFT exact DPO gradient calibration")
    def test_recomputed_dpo_matches_original_loss_and_parameter_gradients(self):
        import torch
        from peft import LoraConfig, get_peft_model, get_peft_model_state_dict, set_peft_model_state_dict
        from transformers import GPT2Config, GPT2LMHeadModel
        torch.manual_seed(73)
        model = get_peft_model(GPT2LMHeadModel(GPT2Config(vocab_size=24, n_layer=1, n_head=2, n_embd=16,
            n_positions=16, bos_token_id=0, eos_token_id=1, resid_pdrop=0, embd_pdrop=0, attn_pdrop=0)),
            LoraConfig(r=2, lora_alpha=4, target_modules=["c_attn"], task_type="CAUSAL_LM", lora_dropout=0), adapter_name="policy")
        model.add_adapter("reference", copy.deepcopy(model.peft_config["policy"]))
        for name, parameter in model.named_parameters():
            if ".policy." in name:
                parameter.data.normal_(std=.1)
        set_peft_model_state_dict(model, get_peft_model_state_dict(model, adapter_name="policy"), adapter_name="reference")
        # Policy must differ from reference to test a nonzero DPO advantage.
        for name, parameter in model.named_parameters():
            if ".policy." in name:
                parameter.data.add_(.03)
        model.train()
        batches = [{"input_ids": torch.tensor([tokens]), "attention_mask": torch.ones(1, len(tokens), dtype=torch.long),
                    "labels": torch.tensor([[-100, -100] + tokens[2:]])}
                   for tokens in ([2, 3, 4, 5, 6], [2, 3, 8, 9, 10])]
        references = [reference_log_probabilities(model, batch) for batch in batches]
        policy = [completion_log_probabilities(model(batch["input_ids"]).logits, batch["labels"])[0] for batch in batches]
        original = dpo_loss(policy[0], policy[1], references[0], references[1], .1).sum() / 3
        original.backward()
        gradients = {name: parameter.grad.clone() for name, parameter in model.named_parameters() if ".policy." in name}
        model.zero_grad(set_to_none=True)
        recomputed = dpo_backward(model, batches[0], batches[1], .1, normalizer=3)
        self.assertFalse(recomputed.requires_grad)
        torch.testing.assert_close(recomputed, original.detach(), rtol=1e-6, atol=1e-8)
        for name, parameter in model.named_parameters():
            if name in gradients:
                torch.testing.assert_close(parameter.grad, gradients[name], rtol=1e-5, atol=1e-8)
            elif ".reference." in name:
                self.assertIsNone(parameter.grad)
        # The function adds to existing accumulated gradients, rather than
        # clearing them or applying the accumulation normalizer twice.
        dpo_backward(model, batches[0], batches[1], .1, normalizer=3)
        for name, parameter in model.named_parameters():
            if name in gradients:
                torch.testing.assert_close(parameter.grad, 2 * gradients[name], rtol=1e-5, atol=2e-8)


if __name__ == "__main__":
    unittest.main()

"""Small CPU experiments for epoch resume and fingerprinted paired comparisons."""

import csv
import json
import random
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset, RandomSampler

from compare_predictions import compare_evaluations, dataset_fingerprint, exact_mcnemar, file_sha256
from experiment_repro import (
    REPRO_VERSION, EpochSeededDataset, capture_rng_state, configure_randomness,
    load_checkpoint, restore_rng_state, resume_randomness, run_config, validate_resume_config,
)
from train_resnet50 import run_epoch


class RandomizedExamples(Dataset):
    def __len__(self):
        return 12

    def __getitem__(self, index):
        return torch.tensor([index / 12, random.random(), float(torch.rand(())), np.random.random()],
                            dtype=torch.float32), index % 2


def toy_experiment(workers, persistent_workers):
    configure_randomness(42, deterministic=True)
    model = nn.Sequential(nn.Linear(4, 5), nn.Dropout(0.3), nn.Linear(5, 2))
    optimizer = torch.optim.SGD(model.parameters(), lr=0.01, momentum=0.8)
    generators = {name: torch.Generator().manual_seed(42 + offset)
                  for offset, name in enumerate(("shuffle", "train_workers", "val_workers"))}
    dataset = EpochSeededDataset(RandomizedExamples(), 42)
    loader = DataLoader(dataset, batch_size=3, num_workers=workers, persistent_workers=persistent_workers,
                        sampler=RandomSampler(dataset, generator=generators["shuffle"]),
                        generator=generators["train_workers"], multiprocessing_context="spawn" if workers else None)
    return model, optimizer, loader, generators


def toy_epoch(model, optimizer, loader, epoch):
    loader.dataset.set_epoch(epoch)
    batches = []
    hook = model.register_forward_pre_hook(lambda module, inputs: batches.append(inputs[0].detach().clone()))
    try:
        run_epoch(model, loader, nn.CrossEntropyLoss(), torch.device("cpu"),
                  torch.amp.GradScaler("cuda", enabled=False), optimizer, accumulation=2)
    finally:
        hook.remove()
    draws = (random.random(), torch.rand(3), np.random.random(3))
    return torch.cat(batches), draws


def shutdown(loader):
    if loader._iterator is not None:
        loader._iterator._shutdown_workers()


class ResumeTests(unittest.TestCase):
    def check_epoch_resume(self, workers, persistent_workers):
        model, optimizer, loader, generators = toy_experiment(workers, persistent_workers)
        resumed_loader = None
        try:
            toy_epoch(model, optimizer, loader, 1)
            checkpoint = {"model": model.state_dict(), "optimizer": optimizer.state_dict(),
                          "rng_state": capture_rng_state(generators), "rng_scheme": REPRO_VERSION}
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "last.pt"
                torch.save(checkpoint, path)
                continuous_samples, continuous_draws = toy_epoch(model, optimizer, loader, 2)
                continuous_model = {name: value.clone() for name, value in model.state_dict().items()}
                continuous_shuffle = generators["shuffle"].get_state().clone()
                resumed_model, resumed_optimizer, resumed_loader, resumed_generators = toy_experiment(workers, persistent_workers)
                saved = load_checkpoint(path)
                resumed_model.load_state_dict(saved["model"])
                resumed_optimizer.load_state_dict(saved["optimizer"])
                self.assertFalse(resume_randomness(saved, resumed_generators))
                restored_samples, restored_draws = toy_epoch(resumed_model, resumed_optimizer, resumed_loader, 2)
                self.assertTrue(torch.equal(continuous_samples, restored_samples))
                self.assertEqual(continuous_draws[0], restored_draws[0])
                self.assertTrue(torch.equal(continuous_draws[1], restored_draws[1]))
                np.testing.assert_array_equal(continuous_draws[2], restored_draws[2])
                self.assertTrue(torch.equal(continuous_shuffle, resumed_generators["shuffle"].get_state()))
                for name, value in resumed_model.state_dict().items():
                    self.assertTrue(torch.equal(continuous_model[name], value), name)
        finally:
            shutdown(loader)
            if resumed_loader is not None:
                shutdown(resumed_loader)

    def test_continuous_matches_resume_without_workers(self):
        self.check_epoch_resume(0, False)

    def test_continuous_matches_resume_with_persistent_spawn_workers(self):
        self.check_epoch_resume(2, True)

    def test_worker_count_and_epoch_do_not_change_sample_identity(self):
        dataset = EpochSeededDataset(RandomizedExamples(), 42)
        dataset.set_epoch(2)
        expected = torch.stack([dataset[index][0] for index in range(len(dataset))])
        loader = DataLoader(dataset, batch_size=3, num_workers=2, persistent_workers=True,
                            multiprocessing_context="spawn")
        try:
            self.assertTrue(torch.equal(expected, torch.cat([features for features, _ in loader])))
            dataset.set_epoch(3)
            next_epoch = torch.cat([features for features, _ in loader])
            self.assertFalse(torch.equal(expected, next_epoch))
            self.assertTrue(torch.equal(next_epoch, torch.stack([dataset[index][0] for index in range(len(dataset))])))
        finally:
            shutdown(loader)

    def test_cuda_rng_restores_when_available(self):
        if not torch.cuda.is_available():
            self.skipTest("CUDA unavailable")
        configure_randomness(42, True)
        state = capture_rng_state({})
        expected = torch.rand(3, device="cuda")
        restore_rng_state(state, {})
        self.assertTrue(torch.equal(expected, torch.rand(3, device="cuda")))

    def test_legacy_checkpoint_warns(self):
        with self.assertWarnsRegex(RuntimeWarning, "Legacy checkpoint"):
            self.assertTrue(resume_randomness({"model": {}}, {}))

    def test_loader_supports_old_torch_and_restricted_loading(self):
        def restricted(path, map_location, weights_only):
            self.assertTrue(weights_only)
            return {"restricted": True}
        with patch("experiment_repro.torch.load", restricted):
            self.assertEqual(load_checkpoint("unused.pt"), {"restricted": True})
        def legacy(path, map_location):
            return {"legacy": True}
        with patch("experiment_repro.torch.load", legacy), self.assertWarnsRegex(RuntimeWarning, "trusted local"):
            self.assertEqual(load_checkpoint("unused.pt"), {"legacy": True})

    def test_config_does_not_record_proxy_credentials_and_rejects_changed_seed(self):
        config = run_config(Namespace(seed=42, proxy="https://user:secret@example.invalid", resume=True, output_dir=Path("output")))
        self.assertNotIn("proxy", config)
        self.assertNotIn("resume", config)
        with self.assertRaisesRegex(ValueError, "seed"):
            validate_resume_config(config, dict(config, seed=43))


def fake_rows(correct):
    classes = ["class-" + str(index) for index in range(6)]
    rows = []
    for index, is_correct in enumerate(correct):
        truth = index % 6
        ranking = [truth] + [label for label in range(6) if label != truth][:4] if is_correct else [label for label in range(6) if label != truth]
        scores = [0.4, 0.3, 0.2, 0.08, 0.02]
        rows.append({"relative_path": f"val/{classes[truth]}/image-{index}.jpg", "true_label": truth,
                     "true_class": classes[truth], "top1_label": ranking[0], "top1_class": classes[ranking[0]],
                     "top1_score": scores[0], "top5_labels": json.dumps(ranking),
                     "top5_classes": json.dumps([classes[label] for label in ranking]),
                     "top5_scores": json.dumps(scores), "sha256": f"{index + 1:064x}"})
    return classes, rows


def write_fake_evaluation(directory, classes, rows, split_hash="1" * 64):
    directory.mkdir()
    with (directory / "per_image.csv").open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    top1 = sum(row["true_label"] == row["top1_label"] for row in rows)
    top5 = sum(row["true_label"] in json.loads(row["top5_labels"]) for row in rows)
    metadata = {"classes": classes, "test_images": len(rows), "test_correct": top1,
                "test_accuracy": top1 / len(rows), "test_top5_accuracy": top5 / len(rows),
                "split_hash": split_hash, "dataset_fingerprint": dataset_fingerprint(rows),
                "predictions_file": "per_image.csv", "predictions_sha256": file_sha256(directory / "per_image.csv"),
                "evaluation_settings": {"preprocessing": "fixture", "autocast_float16": False, "device": "cpu", "batch_size": 3}}
    (directory / "test_metrics.json").write_text(json.dumps(metadata), encoding="utf-8")


class ComparisonTests(unittest.TestCase):
    def test_pairs_align_by_path_and_detect_known_difference(self):
        classes, a = fake_rows([True, False, False, True, False, True])
        _, b = fake_rows([True, True, True, True, False, True])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_fake_evaluation(root / "a", classes, a)
            write_fake_evaluation(root / "b", classes, list(reversed(b)))
            result = compare_evaluations(root / "a", root / "b", 1000, 1)
            self.assertEqual(result["top1"]["only_b_correct"], 2)
            self.assertEqual(result["top1"]["only_a_correct"], 0)
            self.assertAlmostEqual(result["top1"]["difference_b_minus_a"], 2 / 6)
            self.assertEqual(result["top1"]["mcnemar_exact_two_sided_p"], 0.5)

    def test_rejects_duplicate_paths_wrong_truth_content_and_split(self):
        for corruption in ("duplicate", "truth", "content", "split"):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                classes, a = fake_rows([True, False, True])
                _, b = fake_rows([True, False, True])
                if corruption == "duplicate":
                    b[1]["relative_path"] = b[0]["relative_path"]
                elif corruption == "truth":
                    b[0]["true_label"], b[0]["true_class"] = 1, classes[1]
                elif corruption == "content":
                    b[0]["sha256"] = "f" * 64
                write_fake_evaluation(root / "a", classes, a)
                write_fake_evaluation(root / "b", classes, b, "2" * 64 if corruption == "split" else "1" * 64)
                with self.assertRaises(ValueError):
                    compare_evaluations(root / "a", root / "b", 1000)

    def test_rejects_changed_prediction_file(self):
        classes, rows = fake_rows([True])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_fake_evaluation(root / "a", classes, rows)
            write_fake_evaluation(root / "b", classes, rows)
            with (root / "b" / "per_image.csv").open("a") as file:
                file.write("corrupt")
            with self.assertRaisesRegex(ValueError, "checksum"):
                compare_evaluations(root / "a", root / "b", 1000)

    def test_rejects_different_inference_batch_size(self):
        classes, rows = fake_rows([True])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_fake_evaluation(root / "a", classes, rows)
            write_fake_evaluation(root / "b", classes, rows)
            path = root / "b" / "test_metrics.json"
            metadata = json.loads(path.read_text(encoding="utf-8"))
            metadata["evaluation_settings"]["batch_size"] = 8
            path.write_text(json.dumps(metadata), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "batch_size"):
                compare_evaluations(root / "a", root / "b", 1000)

    def test_exact_mcnemar_reference_probabilities(self):
        self.assertEqual(exact_mcnemar(0, 0), 1)
        self.assertEqual(exact_mcnemar(2, 2), 1)
        self.assertAlmostEqual(exact_mcnemar(0, 5), 0.0625)


if __name__ == "__main__":
    unittest.main()

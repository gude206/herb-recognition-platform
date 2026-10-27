"""Engineering unit tests for experiment 3 (synthetic tensors and tiny models only).

These are checks, not experiments: no real dataset, no training, no test-split
evaluation.  Run with::

    python -m unittest discover -s . -p 'test_*.py' -v

or through ``run.py selftest``.
"""

from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset
from torchvision.models.resnet import Bottleneck

import data_eval
import model_ops
import run


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
class TinyClassifier(nn.Module):
    def __init__(self, in_features: int = 8, num_classes: int = 3):
        super().__init__()
        self.backbone = nn.Linear(in_features, 8)
        self.relu = nn.ReLU()
        self.fc = nn.Linear(8, num_classes)

    def forward(self, x):
        return self.fc(self.relu(self.backbone(x)))


class TinyConvNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv = nn.Conv2d(3, 4, 3, padding=1)
        self.bn = nn.BatchNorm2d(4)
        self.relu = nn.ReLU()
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.fc = nn.Linear(4, 5)

    def forward(self, x):
        x = self.relu(self.bn(self.conv(x)))
        x = self.pool(x).flatten(1)
        return self.fc(x)


class RandomDataset(Dataset):
    def __init__(self, length: int, features: int = 8, num_classes: int = 3):
        generator = torch.Generator().manual_seed(0)
        self.data = torch.randn(length, features, generator=generator)
        self.labels = torch.randint(0, num_classes, (length,), generator=generator)

    def __len__(self):
        return len(self.data)

    def __getitem__(self, index):
        return self.data[index], self.labels[index]


class FakeImageFolder:
    """Duck-typed ImageFolder for calibration-index tests."""

    def __init__(self, counts: list[int]):
        self.classes = [f"class_{index}" for index in range(len(counts))]
        self.samples = []
        self.root = "."
        for label, count in enumerate(counts):
            for position in range(count):
                self.samples.append((f"./class_{label}/img_{position}.jpg", label))


def make_bottleneck(inplanes: int = 64, planes: int = 64, stride: int = 1, with_downsample: bool = False):
    downsample = None
    if with_downsample:
        downsample = nn.Sequential(
            nn.Conv2d(inplanes, planes * 4, kernel_size=1, stride=stride, bias=False),
            nn.BatchNorm2d(planes * 4),
        )
    return Bottleneck(inplanes, planes, stride=stride, downsample=downsample)


# --------------------------------------------------------------------------- #
# pruning: keep-count formula and L1 selection
# --------------------------------------------------------------------------- #
class KeepCountTests(unittest.TestCase):
    def test_formula_matches_plan(self):
        cases = {
            (64, 0.10): 58,   # ceil(57.6)
            (64, 0.20): 52,   # ceil(51.2)
            (64, 0.30): 45,   # ceil(44.8)
            (128, 0.30): 90,  # ceil(89.6)
            (256, 0.10): 231,  # ceil(230.4)
            (2048, 0.30): 1434,  # ceil(1433.6)
        }
        for (original, ratio), expected in cases.items():
            self.assertEqual(model_ops.keep_count_for(original, ratio), expected, msg=f"{original}@{ratio}")

    def test_zero_ratio_keeps_everything(self):
        for original in (64, 256, 2048):
            self.assertEqual(model_ops.keep_count_for(original, 0.0), original)

    def test_actual_ratio_never_exceeds_nominal(self):
        for original in (64, 128, 256, 512, 1024, 2048):
            for ratio in (0.10, 0.20, 0.30):
                keep = model_ops.keep_count_for(original, ratio)
                self.assertLessEqual(1.0 - keep / original, ratio + 1e-12)


class L1SelectionTests(unittest.TestCase):
    def test_picks_largest_l1_norms(self):
        weight = torch.zeros(5, 2, 3, 3)
        magnitudes = [0.1, 0.5, 0.3, 0.9, 0.2]
        for index, magnitude in enumerate(magnitudes):
            weight[index] = magnitude
        keep = model_ops.l1_keep_indices(weight, 2)
        self.assertEqual(keep, [1, 3])

    def test_ties_use_lower_original_index_and_sorted_output(self):
        weight = torch.zeros(6, 4)
        for index in range(6):
            weight[index] = 1.0  # every filter has identical L1 norm
        keep = model_ops.l1_keep_indices(weight, 3)
        self.assertEqual(keep, [0, 1, 2])

    def test_output_is_sorted_by_original_index(self):
        weight = torch.zeros(6, 4)
        for index, magnitude in enumerate([1.0, 2.0, 1.0, 2.0, 1.0, 2.0]):
            weight[index] = magnitude
        keep = model_ops.l1_keep_indices(weight, 4)
        self.assertEqual(keep, sorted(keep))
        self.assertEqual(keep, [0, 1, 3, 5])

    def test_rejects_out_of_range_keep_count(self):
        with self.assertRaises(ValueError):
            model_ops.l1_keep_indices(torch.zeros(4, 4), 5)
        with self.assertRaises(ValueError):
            model_ops.l1_keep_indices(torch.zeros(4, 4), 0)


# --------------------------------------------------------------------------- #
# pruning: slicing and bottleneck surgery
# --------------------------------------------------------------------------- #
class SlicingTests(unittest.TestCase):
    def test_sliced_conv_keeps_geometry_and_selects_channels(self):
        source = nn.Conv2d(6, 5, kernel_size=3, stride=2, padding=1, dilation=1, bias=True)
        with torch.no_grad():
            source.weight.copy_(torch.arange(source.weight.numel(), dtype=torch.float32).reshape(source.weight.shape))
            source.bias.copy_(torch.arange(5, dtype=torch.float32))
        keep_in = [0, 2, 4]
        keep_out = [1, 4]
        conv = model_ops._sliced_conv(source, keep_in, keep_out)
        self.assertEqual(conv.in_channels, 3)
        self.assertEqual(conv.out_channels, 2)
        self.assertEqual(conv.stride, source.stride)
        self.assertEqual(conv.padding, source.padding)
        self.assertEqual(conv.dilation, source.dilation)
        self.assertEqual(conv.kernel_size, source.kernel_size)
        expected = source.weight.detach()[keep_out][:, keep_in]
        self.assertTrue(torch.equal(conv.weight.detach(), expected))
        self.assertTrue(torch.equal(conv.bias.detach(), source.bias.detach()[keep_out]))

    def test_sliced_bn_copies_parameters_statistics_and_counter(self):
        source = nn.BatchNorm2d(6)
        with torch.no_grad():
            source.weight.copy_(torch.arange(6, dtype=torch.float32) + 1)
            source.bias.copy_(torch.arange(6, dtype=torch.float32) + 10)
            source.running_mean.copy_(torch.arange(6, dtype=torch.float32) + 20)
            source.running_var.copy_(torch.arange(6, dtype=torch.float32) + 30)
            source.num_batches_tracked.fill_(7)
        keep = [0, 3, 5]
        bn = model_ops._sliced_bn(source, keep)
        self.assertEqual(bn.num_features, 3)
        index = torch.tensor(keep)
        self.assertTrue(torch.equal(bn.weight.detach(), source.weight.detach()[index]))
        self.assertTrue(torch.equal(bn.bias.detach(), source.bias.detach()[index]))
        self.assertTrue(torch.equal(bn.running_mean.detach(), source.running_mean.detach()[index]))
        self.assertTrue(torch.equal(bn.running_var.detach(), source.running_var.detach()[index]))
        self.assertEqual(int(bn.num_batches_tracked), 7)
        self.assertEqual(bn.eps, source.eps)


class BottleneckPruningTests(unittest.TestCase):
    def _check_block(self, stride: int, with_downsample: bool, ratio: float):
        # a Bottleneck keeps inplanes == planes * 4 on the identity path, so the
        # non-downsampling case must start from 256 input channels
        inplanes = 64 if with_downsample else 256
        block = make_bottleneck(inplanes=inplanes, stride=stride, with_downsample=with_downsample).eval()
        pruned, record = model_ops.prune_bottleneck(block, ratio, "test.block")
        keep1 = record["conv1_out_after"]
        keep2 = record["conv2_out_after"]
        self.assertEqual(pruned.conv1.out_channels, keep1)
        self.assertEqual(pruned.bn1.num_features, keep1)
        self.assertEqual(pruned.conv2.in_channels, keep1)
        self.assertEqual(pruned.conv2.out_channels, keep2)
        self.assertEqual(pruned.bn2.num_features, keep2)
        self.assertEqual(pruned.conv3.in_channels, keep2)
        self.assertEqual(pruned.conv3.out_channels, block.conv3.out_channels)
        self.assertEqual(pruned.bn3.num_features, block.bn3.num_features)
        self.assertEqual(pruned.conv2.stride, block.conv2.stride)
        self.assertEqual(pruned.conv2.padding, block.conv2.padding)
        self.assertFalse(pruned.training, "replaced block must be back in eval mode")
        for name in ("conv1", "bn1", "conv2", "bn2", "conv3", "bn3"):
            self.assertFalse(getattr(pruned, name).training, msg=f"{name} must be back in eval mode")

        height = 56
        probe = torch.randn(2, inplanes, height, height)
        with torch.no_grad():
            output = pruned(probe)
        expected_height = height if stride == 1 else math.ceil(height / 2)
        self.assertEqual(tuple(output.shape), (2, block.conv3.out_channels, expected_height, expected_height))
        self.assertTrue(torch.isfinite(output).all())

        if with_downsample:
            self.assertEqual(pruned.downsample[0].out_channels, block.downsample[0].out_channels)
            self.assertEqual(
                pruned.downsample[0].weight.shape, block.downsample[0].weight.shape,
                msg="residual downsampling branch must stay unchanged",
            )
        else:
            self.assertIsNone(pruned.downsample)
        return block, pruned, record

    def test_identity_residual_path(self):
        block, pruned, record = self._check_block(stride=1, with_downsample=False, ratio=0.30)
        self.assertEqual(record["conv1_out_before"], 64)
        self.assertEqual(record["conv2_out_before"], 64)
        self.assertEqual(record["conv1_out_after"], 45)
        self.assertEqual(record["conv2_out_after"], 45)
        self.assertAlmostEqual(record["conv1_actual_ratio"], 1 - 45 / 64, places=12)

    def test_projection_residual_path(self):
        self._check_block(stride=2, with_downsample=True, ratio=0.20)

    def test_zero_ratio_rebuild_is_identity(self):
        torch.manual_seed(7)
        block = make_bottleneck(stride=1, with_downsample=True).eval()
        pruned, record = model_ops.prune_bottleneck(block, 0.0, "test.block")
        self.assertEqual(record["conv1_actual_ratio"], 0.0)
        self.assertEqual(record["conv2_actual_ratio"], 0.0)
        for name in ("conv1", "conv2", "conv3", "bn1", "bn2", "bn3"):
            original = getattr(block, name)
            rebuilt = getattr(pruned, name)
            for (key, value), (key2, value2) in zip(original.state_dict().items(), rebuilt.state_dict().items()):
                self.assertEqual(key, key2)
                self.assertTrue(torch.equal(value, value2), msg=f"{name}.{key} differs at ratio 0")
        probe = torch.randn(2, block.conv1.in_channels, 32, 32)
        with torch.no_grad():
            self.assertTrue(torch.allclose(block(probe), pruned(probe), atol=1e-6))

    def test_kept_channel_weights_follow_selection(self):
        block = make_bottleneck().eval()
        pruned, record = model_ops.prune_bottleneck(block, 0.30, "test.block")
        keep1 = torch.tensor(record["keep1"])
        keep2 = torch.tensor(record["keep2"])
        self.assertTrue(torch.equal(pruned.conv1.weight.detach(), block.conv1.weight.detach()[keep1]))
        self.assertTrue(torch.equal(pruned.conv2.weight.detach(), block.conv2.weight.detach()[keep2][:, keep1]))
        self.assertTrue(torch.equal(pruned.conv3.weight.detach(), block.conv3.weight.detach()[:, keep2]))

    def test_rejects_grouped_convolution(self):
        block = make_bottleneck()
        block.conv2 = nn.Conv2d(64, 64, 3, padding=1, groups=2, bias=False)
        with self.assertRaises(ValueError):
            model_ops.prune_bottleneck(block, 0.1, "test.block")


# --------------------------------------------------------------------------- #
# parameter / FLOP accounting
# --------------------------------------------------------------------------- #
class AccountingTests(unittest.TestCase):
    def test_parameters_and_macs_match_hand_computation(self):
        model = nn.Sequential(
            nn.Conv2d(3, 4, kernel_size=3, stride=1, padding=1, bias=False),
            nn.BatchNorm2d(4),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d(1),
            nn.Flatten(),
            nn.Linear(4, 2),
        ).eval()
        params = data_eval.count_parameters(model)
        expected_params = 3 * 4 * 3 * 3 + (4 + 4) + (4 * 2 + 2)  # conv + bn(weight,bias) + linear(weight,bias)
        self.assertEqual(params, expected_params)
        cost = data_eval.conv_linear_macs(model, input_size=(1, 3, 224, 224))
        conv_macs = 3 * 4 * 3 * 3 * 224 * 224
        linear_macs = 4 * 2
        self.assertEqual(cost["total_macs"], conv_macs + linear_macs)
        self.assertEqual(cost["total_flops"], 2 * (conv_macs + linear_macs))
        self.assertEqual(len(cost["modules"]), 2, msg="BN/ReLU/pooling must not be counted")

    def test_parameters_drop_after_bottleneck_pruning(self):
        block = make_bottleneck().eval()
        before = data_eval.count_parameters(block)
        pruned, _ = model_ops.prune_bottleneck(block, 0.30, "test.block")
        after = data_eval.count_parameters(pruned)
        self.assertLess(after, before)


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #
class MetricTests(unittest.TestCase):
    def test_confusion_matrix_and_macro_metrics(self):
        import numpy as np

        y_true = np.array([0, 0, 1, 1, 2])
        y_pred = np.array([0, 1, 1, 1, 0])
        cm = data_eval.confusion_matrix(y_true, y_pred, num_classes=3)
        self.assertEqual(cm.shape, (3, 3))
        self.assertEqual(int(cm[0, 0]), 1)
        self.assertEqual(int(cm[0, 1]), 1)
        self.assertEqual(int(cm[2, 1]), 0)
        metrics = data_eval.macro_metrics(cm)
        # class 0: tp1 pred2 support2 -> p=0.5 r=0.5 f1=0.5
        # class 1: tp2 pred3 support2 -> p=2/3 r=1.0 f1=0.8
        # class 2: tp0 pred0 support1 -> p=0 r=0 f1=0
        self.assertAlmostEqual(metrics["per_class_precision"][0], 0.5)
        self.assertAlmostEqual(metrics["per_class_recall"][0], 0.5)
        self.assertAlmostEqual(metrics["per_class_f1"][0], 0.5)
        self.assertAlmostEqual(metrics["per_class_f1"][1], 0.8)
        self.assertAlmostEqual(metrics["per_class_f1"][2], 0.0)
        self.assertAlmostEqual(metrics["macro_precision"], (0.5 + 2 / 3 + 0.0) / 3)
        self.assertAlmostEqual(metrics["macro_recall"], (0.5 + 1.0 + 0.0) / 3)
        self.assertAlmostEqual(metrics["macro_f1"], (0.5 + 0.8 + 0.0) / 3)

    def test_zero_denominator_counts_as_zero(self):
        import numpy as np

        cm = np.zeros((3, 3), dtype=np.int64)
        cm[0, 0] = 2
        metrics = data_eval.macro_metrics(cm)
        self.assertEqual(metrics["per_class_precision"][2], 0.0)
        self.assertEqual(metrics["per_class_recall"][2], 0.0)
        self.assertEqual(metrics["per_class_f1"][2], 0.0)


# --------------------------------------------------------------------------- #
# validation platform (early stopping)
# --------------------------------------------------------------------------- #
class PlatformTests(unittest.TestCase):
    def _state(self, counters: run.PlatformCounters):
        return counters.state()

    def test_all_five_conditions_are_required(self):
        config = run.load_config()
        counters = run.PlatformCounters(config)
        counters.epoch = 12
        counters.ce_stale = 8
        counters.top1_stale = 8
        counters.lr_reductions = 2
        counters.epochs_since_reduction = 3
        stopped, checks = counters.should_stop()
        self.assertTrue(stopped)
        self.assertTrue(all(check["met"] for check in checks))

        counters.lr_reductions = 1
        stopped, checks = counters.should_stop()
        self.assertFalse(stopped)
        self.assertEqual(sum(1 for check in checks if not check["met"]), 1)

        counters.lr_reductions = 2
        counters.epoch = 4
        stopped, _ = counters.should_stop()
        self.assertFalse(stopped, msg="minimum 5 epochs must be enforced")

        counters.epoch = 12
        counters.epochs_since_reduction = 2
        stopped, _ = counters.should_stop()
        self.assertFalse(stopped, msg="3 epochs after the last reduction are required")

    def test_earliest_possible_stop_is_about_epoch_twelve(self):
        """Feed perfectly flat metrics through the real scheduler and counters."""
        config = run.load_config()
        model = TinyClassifier()
        optimizer = run.build_optimizer(model, config)
        scheduler = run.build_scheduler(optimizer, config)
        counters = run.PlatformCounters(config)
        stop_epoch = None
        for epoch in range(1, 40):
            before = [group["lr"] for group in optimizer.param_groups]
            scheduler.step(1.0)  # never improves
            after = [group["lr"] for group in optimizer.param_groups]
            reduced = any(after_lr < before_lr for before_lr, after_lr in zip(before, after))
            counters.update(1.0, 0.10, reduced)
            stopped, _ = counters.should_stop()
            if stopped:
                stop_epoch = epoch
                break
        self.assertEqual(stop_epoch, 12, msg=f"flat metrics should stop at epoch 12, got {stop_epoch}")
        self.assertEqual(counters.lr_reductions, 2)
        self.assertEqual(counters.ce_stale, 11)

    def test_improving_run_does_not_stop_early(self):
        config = run.load_config()
        model = TinyClassifier()
        optimizer = run.build_optimizer(model, config)
        scheduler = run.build_scheduler(optimizer, config)
        counters = run.PlatformCounters(config)
        ce = 1.0
        top1 = 0.10
        for _ in range(30):
            before = [group["lr"] for group in optimizer.param_groups]
            scheduler.step(ce)
            after = [group["lr"] for group in optimizer.param_groups]
            reduced = any(after_lr < before_lr for before_lr, after_lr in zip(before, after))
            counters.update(ce, top1, reduced)
            ce *= 0.98
            top1 += 0.002
            stopped, _ = counters.should_stop()
            self.assertFalse(stopped, msg="a still-improving run must not be stopped")

    def test_counter_serialisation_round_trip(self):
        config = run.load_config()
        counters = run.PlatformCounters(config)
        counters.update(1.0, 0.1, False)
        state = counters.state()
        restored = run.PlatformCounters(config)
        restored.__dict__.update(state)
        self.assertEqual(restored.state(), state)


# --------------------------------------------------------------------------- #
# gradient accumulation / last partial group
# --------------------------------------------------------------------------- #
class AccumulationTests(unittest.TestCase):
    def test_last_partial_group_keeps_real_samples(self):
        config = run.load_config()
        dataset = RandomDataset(5, features=8, num_classes=3)
        loader = DataLoader(dataset, batch_size=4, shuffle=False, drop_last=False)
        model = TinyClassifier()
        initial_state = {key: value.detach().clone() for key, value in model.state_dict().items()}
        optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
        result = run.train_one_epoch(model, loader, optimizer, torch.device("cpu"), accumulation=4)
        self.assertEqual(result["samples"], 5)

        expected_model = TinyClassifier()
        expected_model.load_state_dict(initial_state)
        cpu = torch.optim.SGD(expected_model.parameters(), lr=0.1)
        cpu.zero_grad(set_to_none=True)
        criterion = nn.CrossEntropyLoss()
        loss = criterion(expected_model(dataset.data), dataset.labels)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(list(expected_model.parameters()), 1.0)
        cpu.step()
        for (name, parameter), (_, reference) in zip(model.named_parameters(), expected_model.named_parameters()):
            self.assertTrue(
                torch.allclose(parameter, reference, atol=1e-6),
                msg=f"accumulated update differs from the true mean-over-samples update at {name}",
            )

    def test_two_full_groups_plus_remainder(self):
        dataset = RandomDataset(9, features=8, num_classes=3)
        loader = DataLoader(dataset, batch_size=2, shuffle=False, drop_last=False)
        self.assertEqual(len(loader), 5)
        model = TinyClassifier()
        optimizer = torch.optim.SGD(model.parameters(), lr=0.01)
        result = run.train_one_epoch(model, loader, optimizer, torch.device("cpu"), accumulation=2)
        self.assertEqual(result["samples"], 9)
        parameters = [parameter.detach() for parameter in model.parameters()]
        self.assertTrue(all(torch.isfinite(value).all() for value in parameters))


# --------------------------------------------------------------------------- #
# calibration sampling
# --------------------------------------------------------------------------- #
class CalibrationTests(unittest.TestCase):
    def test_tiers_are_nested_and_per_class(self):
        folder = FakeImageFolder([10, 12, 20])
        indices_2, rows_2 = data_eval.calibration_indices(folder, 2)
        indices_5, _ = data_eval.calibration_indices(folder, 5)
        indices_10, _ = data_eval.calibration_indices(folder, 10)
        self.assertEqual(len(indices_2), 6)
        self.assertEqual(len(indices_5), 15)
        self.assertEqual(len(indices_10), 30)
        self.assertTrue(set(indices_2) <= set(indices_5) <= set(indices_10))
        labels_2 = [folder.samples[index][1] for index in indices_2]
        self.assertEqual(sorted(set(labels_2)), [0, 1, 2])
        self.assertEqual(len(rows_2), 3)
        self.assertTrue(all(row["selected"] == 2 for row in rows_2))

    def test_sampling_is_reproducible(self):
        folder = FakeImageFolder([30, 30])
        first, _ = data_eval.calibration_indices(folder, 5, seed=42)
        second, _ = data_eval.calibration_indices(folder, 5, seed=42)
        self.assertEqual(first, second)
        different, _ = data_eval.calibration_indices(folder, 5, seed=43)
        self.assertNotEqual(first, different)

    def test_insufficient_class_stops_instead_of_borrowing(self):
        folder = FakeImageFolder([10, 1])
        with self.assertRaises(ValueError):
            data_eval.calibration_indices(folder, 2)


# --------------------------------------------------------------------------- #
# deterministic per-sample augmentation
# --------------------------------------------------------------------------- #
class EpochSeedTests(unittest.TestCase):
    def setUp(self):
        class RandomTensorDataset(Dataset):
            def __len__(self):
                return 4

            def __getitem__(self, index):
                return torch.rand(1).item(), index

        self.dataset = RandomTensorDataset()

    def test_same_epoch_and_index_is_reproducible(self):
        wrapped = data_eval.EpochSeededDataset(self.dataset, seed=42)
        wrapped.set_epoch(3)
        first = wrapped[2]
        second = wrapped[2]
        self.assertEqual(first, second)

    def test_different_epoch_changes_augmentation(self):
        wrapped = data_eval.EpochSeededDataset(self.dataset, seed=42)
        wrapped.set_epoch(1)
        epoch_one = [wrapped[index][0] for index in range(4)]
        wrapped.set_epoch(2)
        epoch_two = [wrapped[index][0] for index in range(4)]
        self.assertNotEqual(epoch_one, epoch_two)

    def test_sequence_does_not_depend_on_access_order(self):
        wrapped = data_eval.EpochSeededDataset(self.dataset, seed=42)
        wrapped.set_epoch(5)
        forward = [wrapped[index][0] for index in range(4)]
        wrapped.set_epoch(5)
        backward = [wrapped[index][0] for index in reversed(range(4))][::-1]
        self.assertEqual(forward, backward)


# --------------------------------------------------------------------------- #
# export and quantization plumbing
# --------------------------------------------------------------------------- #
class ExportTests(unittest.TestCase):
    def test_trace_export_reloads_at_batch_one_and_eight(self):
        model = TinyConvNet().eval()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tiny.pt"
            info = model_ops.export_torchscript(model, path, batch_size=1)
            self.assertEqual(info["method"], "torch.jit.trace")
            self.assertFalse(info["freeze"])
            self.assertGreater(info["bytes"], 0)
            report = model_ops.verify_export(path, model, batch_sizes=(1, 8))
            self.assertTrue(report["all_consistent"], msg=json.dumps(report, indent=2))
            for check in report["batch_checks"]:
                self.assertEqual(check["expected_shape"], [check["batch_size"], 5])

    def test_export_and_reload_inside_non_ascii_directory(self):
        """TorchScript C++ path handling fails on Chinese paths; the file handle path works."""
        model = TinyConvNet().eval()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "实验三" / "中文目录" / "tiny.pt"
            model_ops.export_torchscript(model, target, batch_size=1)
            self.assertTrue(target.is_file())
            report = model_ops.verify_export(target, model, batch_sizes=(1, 8))
            self.assertTrue(report["all_consistent"], msg=json.dumps(report, indent=2))

    def test_sha256_helper_matches_hashlib(self):
        import hashlib

        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(b"experiment3" * 1000)
            name = handle.name
        try:
            expected = hashlib.sha256(Path(name).read_bytes()).hexdigest()
            self.assertEqual(data_eval.file_sha256(Path(name)), expected)
        finally:
            Path(name).unlink()


class QuantizationTests(unittest.TestCase):
    def test_static_quantization_converts_conv_and_linear(self):
        torch.backends.quantized.engine = "fbgemm"
        config = run.load_config()
        model = TinyConvNet().eval()
        calibration = [torch.randn(4, 3, 224, 224) for _ in range(2)]
        quantized = model_ops.quantize_static_fx(model, config, calibration)
        inspection = model_ops.inspect_quantization(quantized)
        self.assertGreaterEqual(inspection["quantized_conv_count"], 1)
        self.assertGreaterEqual(inspection["quantized_linear_count"], 1)
        self.assertEqual(inspection["float_conv_count"], 0)
        self.assertEqual(inspection["float_linear_count"], 0)
        with model_ops.relaxed_determinism(True), torch.no_grad():
            output = quantized(torch.randn(1, 3, 224, 224))
        self.assertEqual(tuple(output.shape), (1, 5))
        self.assertTrue(torch.isfinite(output).all())

    def test_quantized_model_can_be_traced_and_reloaded(self):
        torch.backends.quantized.engine = "fbgemm"
        config = run.load_config()
        model = TinyConvNet().eval()
        calibration = [torch.randn(2, 3, 224, 224)]
        quantized = model_ops.quantize_static_fx(model, config, calibration)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tiny_int8.pt"
            model_ops.export_torchscript(quantized, path, batch_size=1)
            report = model_ops.verify_export(
                path, quantized, batch_sizes=(1, 8), relax_determinism=True
            )
            self.assertTrue(report["all_consistent"], msg=json.dumps(report, indent=2))

    def test_quantized_rebuild_from_a_is_deterministic(self):
        """Q is rebuilt at freeze time instead of pickled; the rebuild must be identical."""
        torch.backends.quantized.engine = "fbgemm"
        config = run.load_config()
        calibration = [torch.randn(2, 3, 224, 224, generator=torch.Generator().manual_seed(5))]
        source = TinyConvNet().eval()  # same weights for both rebuilds
        first = model_ops.quantize_static_fx(source, config, calibration)
        second = model_ops.quantize_static_fx(source, config, calibration)
        probe = torch.randn(1, 3, 224, 224)
        with model_ops.relaxed_determinism(True), torch.no_grad():
            self.assertTrue(torch.equal(first(probe), second(probe)))

    def test_observers_carry_the_fixed_settings(self):
        # the qconfig must be built from the frozen config, not from code constants
        qconfig = model_ops.make_qconfig(run.load_config()["quantization"])
        activation = qconfig.activation()  # _PartialWrapper -> concrete observer
        weight = qconfig.weight()
        self.assertEqual(activation.dtype, torch.quint8)
        self.assertEqual(activation.qscheme, torch.per_tensor_affine)
        self.assertEqual(activation.quant_min, 0)
        self.assertEqual(activation.quant_max, 255)  # revision 2: full quint8 range
        self.assertFalse(activation.reduce_range)
        self.assertEqual(activation.bins, 2048)
        self.assertEqual(weight.dtype, torch.qint8)
        self.assertEqual(weight.qscheme, torch.per_channel_symmetric)
        self.assertEqual(weight.ch_axis, 0)
        self.assertEqual(weight.quant_min, -128)
        self.assertEqual(weight.quant_max, 127)

    def test_quantizer_values_come_from_config_not_code(self):
        """Regression: a hard-coded quant_max silently ignored a config revision."""
        config = run.load_config()
        from_config = model_ops.make_qconfig(config["quantization"]).activation()
        self.assertEqual(from_config.quant_max, int(config["quantization"]["activation_quant_max"]))
        self.assertEqual(from_config.quant_min, int(config["quantization"]["activation_quant_min"]))
        self.assertEqual(from_config.bins, int(config["quantization"]["activation_observer_bins"]))
        # a different recorded value must change the built observer
        alternate = json.loads(json.dumps(config["quantization"]))
        alternate["activation_quant_max"] = 127
        alternate_observer = model_ops.make_qconfig(alternate).activation()
        self.assertEqual(alternate_observer.quant_max, 127)
        self.assertNotEqual(alternate_observer.quant_max, from_config.quant_max)


# --------------------------------------------------------------------------- #
# frozen config / permissions / model guard
# --------------------------------------------------------------------------- #
class FrozenConfigTests(unittest.TestCase):
    def test_config_hash_matches_recorded_value(self):
        recorded = run.HASH_PATH.read_text(encoding="utf-8").strip()
        self.assertEqual(run.config_sha256(), recorded)

    def test_permissions_bound_to_config_hash(self):
        permissions = run.load_permissions()
        self.assertEqual(permissions["config_hash"], run.config_sha256())

    def test_stage_gating_matches_authorized_scope(self):
        """Stages 4-9 are open after the option-B approval; GitHub sync is not."""
        for permission in (
            "full_data_audit",
            "baseline_validation",
            "quantization_selection",
            "pruning_screening",
            "full_training",
            "freeze_models",
            "final_evaluation",
            "timing_benchmark",
        ):
            self.assertTrue(run.require(permission)["permissions"][permission], msg=permission)
        with self.assertRaises(SystemExit):
            run.require("github_sync")
        for permission in ("selftest", "smoke", "config_check"):
            self.assertTrue(run.require(permission)["permissions"][permission])

    def test_plan_targets_and_fixed_values(self):
        config = run.load_config()
        # revision 2 (user-approved option B): activation upper bound 255
        self.assertEqual(config["quantization"]["activation_quant_max"], 255)
        self.assertEqual(config["quantization"]["activation_quant_min"], 0)
        self.assertFalse(config["quantization"]["activation_reduce_range"])
        self.assertEqual(config["quantization"]["weight_quant_min"], -128)
        self.assertEqual(config["quantization"]["weight_quant_max"], 127)
        self.assertEqual(config["pruning"]["ratios"], [0.10, 0.20, 0.30])
        self.assertEqual(config["calibration"]["tiers_per_class"], [2, 5, 10])
        self.assertEqual(config["calibration"]["tiers_total"], [600, 1500, 3000])
        self.assertEqual(config["finetune"]["physical_batch"], 4)
        self.assertEqual(config["finetune"]["grad_accumulation"], 4)
        self.assertEqual(config["finetune"]["backbone_lr"], 2e-05)
        self.assertEqual(config["finetune"]["head_lr"], 2e-04)
        self.assertEqual(config["finetune"]["grad_clip_l2_norm"], 1.0)
        self.assertEqual(config["finetune"]["dataloader"]["workers"], 2)
        self.assertEqual(config["finetune"]["val_batch"], 8)
        self.assertIsNone(config["finetune"]["max_epochs"])
        self.assertEqual(config["params_and_flops"]["flops"]["mac_to_flops"], 2)
        self.assertEqual(config["environment"]["cpu_threads"], 4)
        self.assertEqual(config["environment"]["cublas_workspace_config"], ":4096:8")
        self.assertFalse(config["environment"]["amp"])
        self.assertFalse(config["environment"]["tf32"])
        self.assertTrue(config["environment"]["deterministic"])
        self.assertFalse(config["environment"]["cudnn_benchmark"])

    def test_plan_compliance_every_fixed_value(self):
        """One assertion per fixed value in the approved plan (config is the record)."""
        config = run.load_config()

        # environment and data
        env = config["environment"]
        self.assertEqual(env["python_version"], "3.10.20")
        self.assertEqual(env["torch"], "2.5.1+cu121")
        self.assertEqual(env["torchvision"], "0.20.1+cu121")
        self.assertEqual(env["numpy"], "2.2.5")
        self.assertEqual(env["pillow"], "11.2.1")
        self.assertEqual(env["matplotlib"], "3.10.3")
        self.assertEqual(env["device_train"], "cuda:0")
        self.assertEqual(env["cpu_interop_threads"], 1)
        self.assertFalse(env["fp16"])
        data = config["data"]
        self.assertEqual((data["train_images"], data["val_images"], data["test_images"]), (36324, 11030, 4735))
        self.assertEqual(data["classes"], 300)
        self.assertTrue(data["no_resplit"])
        self.assertTrue(data["no_image_deletion"])
        self.assertTrue(data["no_label_change"])

        # preprocessing
        pre = config["preprocessing"]
        self.assertEqual(pre["eval_resize_short_side"], 256)
        self.assertEqual(pre["eval_center_crop"], 224)
        self.assertEqual(pre["train_random_resized_crop"], 224)
        self.assertEqual(pre["train_scale"], [0.8, 1.0])
        self.assertEqual(pre["train_ratio"], [0.9, 1.1])
        self.assertEqual(pre["train_horizontal_flip_p"], 0.5)
        self.assertEqual(pre["interpolation"], "bilinear")
        self.assertTrue(pre["antialias"])
        self.assertEqual(pre["normalize_mean"], [0.485, 0.456, 0.406])
        self.assertEqual(pre["normalize_std"], [0.229, 0.224, 0.225])
        self.assertEqual(pre["seed"], 42)

        # quantization
        quant = config["quantization"]
        self.assertEqual(quant["device"], "cpu")
        self.assertEqual(quant["engine"], "fbgemm")
        self.assertEqual(quant["activation_observer"], "HistogramObserver")
        self.assertEqual(quant["activation_observer_bins"], 2048)
        self.assertEqual(quant["activation_dtype"], "quint8")
        self.assertEqual(quant["activation_qscheme"], "per_tensor_affine")
        self.assertEqual(quant["weight_observer"], "PerChannelMinMaxObserver")
        self.assertEqual(quant["weight_dtype"], "qint8")
        self.assertEqual(quant["weight_qscheme"], "per_channel_symmetric")
        self.assertEqual(quant["weight_ch_axis"], 0)
        self.assertFalse(quant["qat"])
        self.assertFalse(quant["post_quant_finetune"])
        self.assertTrue(quant["rebuild_from_a_per_candidate"])
        self.assertEqual(config["calibration"]["per_class_permutation_seed"], 42)
        self.assertTrue(config["calibration"]["nested"])
        self.assertEqual(config["targets"]["quantization"]["primary"], "验证 Top-1 下降 ≤ 2 个百分点")

        # pruning
        prune = config["pruning"]
        self.assertEqual(prune["keep_channels_formula"], "ceil((1 - ratio) * 原通道数)")
        self.assertTrue(prune["independent_from_a"])
        self.assertTrue(prune["no_cumulative"])
        self.assertIn("只选择一档进行正式微调", prune["screening"])
        self.assertIn("conv3 输出、bn3、残差下采样分支、首层卷积、最终分类层", prune["slicing"]["unchanged"])
        self.assertEqual(config["targets"]["pruning"]["channel_keep_ratio_min"], 0.70)
        self.assertEqual(config["targets"]["pruning"]["main_operator_flops_drop_min"], 0.30)
        self.assertEqual(config["targets"]["pruning"]["top1_drop_max_percentage_points"], 3.0)

        # fine-tune
        ft = config["finetune"]
        self.assertEqual(ft["seed_reset"], 42)
        self.assertEqual(ft["loss"], "普通交叉熵，无类别权重，无标签平滑")
        self.assertEqual(ft["effective_batch"], 16)
        self.assertEqual(ft["optimizer"], "AdamW")
        self.assertEqual(ft["betas"], [0.9, 0.999])
        self.assertAlmostEqual(ft["eps"], 1e-8)
        self.assertAlmostEqual(ft["weight_decay"], 1e-4)
        self.assertFalse(ft["amsgrad"])
        self.assertEqual(ft["dataloader"]["multiprocessing_context"], "spawn")
        self.assertTrue(ft["dataloader"]["persistent_workers"])
        self.assertEqual(ft["dataloader"]["prefetch_factor"], 2)
        self.assertTrue(ft["dataloader"]["pin_memory"])
        self.assertFalse(ft["val_shuffle"])
        scheduler = ft["scheduler"]
        self.assertEqual(scheduler["type"], "ReduceLROnPlateau")
        self.assertEqual(scheduler["mode"], "min")
        self.assertEqual(scheduler["factor"], 0.5)
        self.assertEqual(scheduler["patience"], 3)
        self.assertEqual(scheduler["threshold"], 0.001)
        self.assertEqual(scheduler["threshold_mode"], "rel")
        self.assertEqual(scheduler["cooldown"], 0)
        self.assertEqual(scheduler["eps"], 0)
        self.assertAlmostEqual(scheduler["min_lr_backbone"], 2e-7)
        self.assertAlmostEqual(scheduler["min_lr_head"], 2e-6)
        self.assertEqual(len(ft["stop_conditions_all_required"]), 5)
        self.assertFalse(ft["extra_unpruned_control"])

        # export / evaluation / timing
        export = config["export"]
        self.assertEqual(export["method"], "trace")
        self.assertFalse(export["extra_freeze"])
        self.assertFalse(export["extra_inference_optimization"])
        self.assertEqual(export["verify_batch_sizes"], [1, 8])
        evaluation = config["evaluation"]
        self.assertEqual(evaluation["test_batch"], 1)
        self.assertEqual(evaluation["test_images"], 4735)
        self.assertEqual(evaluation["device_model_pairs"], {"cpu": ["A", "Q"], "cuda:0": ["A", "P"]})
        timing = config["timing"]
        self.assertEqual(timing["device_model_pairs"], {"cpu": ["A", "Q"], "cuda:0": ["A", "P"]})
        self.assertEqual(timing["batch_sizes"], [1, 8])
        self.assertEqual(timing["warmup_iterations"], 40)
        self.assertEqual(timing["measured_iterations"], 100)
        self.assertEqual(timing["rounds"], 3)
        self.assertIn("前 32 张", timing["input_source"])

        # scope guards
        self.assertEqual(config["scope_authorization"]["authorized_stages"], [1, 2, 3, 4, 5, 6, 7, 8, 9])
        self.assertTrue(config["scope_authorization"]["long_tasks_authorized"])
        self.assertTrue(config["determinism_exception"]["requires_user_confirmation"])
        revisions = config["config_revisions"]
        self.assertEqual([r["revision"] for r in revisions], [1, 2])
        history = json.loads((run.EXPERIMENT_DIR / "config_revisions.json").read_text(encoding="utf-8"))
        self.assertEqual(history["revisions"][1]["sha256"], run.config_sha256())
        self.assertEqual(history["revisions"][0]["sha256"], "7c833d491e8643fe7d06c17ee31772b493f3d03aaffedbb8a55c5c7c4c6ba8d3")

    def test_speedup_option_b_is_recorded_and_scoped(self):
        """Option B: training determinism relaxed, evaluation determinism kept."""
        config = run.load_config()
        self.assertTrue(config["environment"]["deterministic"])
        self.assertFalse(config["environment"]["train_deterministic"])
        self.assertEqual(config["evaluation"]["dataloader_workers"], 2)
        self.assertEqual(config["speedup_decision"]["approved_by_user"][:4], "2026")
        self.assertEqual(len(config["speedup_decision"]["changes"]), 2)
        self.assertIn("FP32；不启用 AMP/FP16/TF32", config["speedup_decision"]["unchanged"])
        # the context manager must restore BOTH flags, not leave them relaxed
        algorithms_before = torch.are_deterministic_algorithms_enabled()
        cudnn_before = torch.backends.cudnn.deterministic
        try:
            torch.backends.cudnn.deterministic = True
            torch.use_deterministic_algorithms(True)
            with model_ops.relaxed_determinism(True):
                self.assertFalse(torch.are_deterministic_algorithms_enabled())
                self.assertFalse(torch.backends.cudnn.deterministic)
            self.assertTrue(torch.are_deterministic_algorithms_enabled())
            self.assertTrue(torch.backends.cudnn.deterministic)
            with model_ops.relaxed_determinism(False):
                self.assertTrue(torch.are_deterministic_algorithms_enabled())
                self.assertTrue(torch.backends.cudnn.deterministic)
        finally:
            torch.use_deterministic_algorithms(algorithms_before)
            torch.backends.cudnn.deterministic = cudnn_before


class ModelGuardTests(unittest.TestCase):
    def test_wrong_model_hash_is_rejected_before_loading(self):
        config = run.load_config()
        config = json.loads(json.dumps(config))
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pt") as handle:
            handle.write(b"not the real checkpoint")
            name = handle.name
        try:
            config["paths"]["model_a_best"] = name
            with self.assertRaises(ValueError) as context:
                model_ops.load_fp32_model(config)
            self.assertIn("does not match the approved", str(context.exception))
        finally:
            Path(name).unlink()


if __name__ == "__main__":
    unittest.main(verbosity=2)

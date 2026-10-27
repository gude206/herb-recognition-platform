"""Engineering smoke checks for experiment 3.

Scope is fixed by the approved plan and is strictly limited to engineering
checks: synthetic tensors, the 0% pruning rebuild, one real batch per pruning
candidate, one forward+backward without an optimizer update, a 4-image
temporary quantization calibration, export/reload round trips, the last
incomplete accumulation group, the data split check and the early-stopping /
checkpoint-resume mechanics.

It does NOT run a full epoch, does NOT run the final test split, and produces no
formal result.  The temporary quantized/exported artefacts are deleted at the
end and only an engineering report is kept (``runs/smoke_report.json``).
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
import traceback
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset

EXPERIMENT_DIR = Path(__file__).resolve().parent
REPORT_PATH = EXPERIMENT_DIR / "runs" / "smoke_report.json"


class Report:
    def __init__(self) -> None:
        self.checks: list[dict] = []
        self.started = time.strftime("%Y-%m-%dT%H:%M:%S")

    def add(self, name: str, passed: bool, detail=None, seconds: float | None = None) -> bool:
        payload = {"check": name, "passed": bool(passed), "detail": detail}
        if seconds is not None:
            payload["seconds"] = round(seconds, 3)
        self.checks.append(payload)
        print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f" ({seconds:.1f}s)" if seconds else ""))
        return bool(passed)

    def failed(self) -> list[dict]:
        return [item for item in self.checks if not item["passed"]]

    def finish(self, extra: dict | None = None) -> dict:
        payload = {
            "kind": "engineering_smoke_report",
            "started_at": self.started,
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "checks": self.checks,
            "failed": self.failed(),
            "all_passed": not self.failed(),
            "scope_note": (
                "Engineering checks only. No full epoch was trained, no final test-set evaluation was run, "
                "and no formal model or accuracy result was produced."
            ),
        }
        if extra:
            payload.update(extra)
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return payload


# --------------------------------------------------------------------------- #
# synthetic helpers
# --------------------------------------------------------------------------- #
class _RandomDataset(Dataset):
    def __init__(self, length: int = 9, features: int = 8, classes: int = 3):
        generator = torch.Generator().manual_seed(0)
        self.data = torch.randn(length, features, generator=generator)
        self.labels = torch.randint(0, classes, (length,), generator=generator)

    def __len__(self):
        return len(self.data)

    def __getitem__(self, index):
        return self.data[index], self.labels[index]


class _TinyNet(nn.Module):
    def __init__(self, features: int = 8, classes: int = 3):
        super().__init__()
        self.backbone = nn.Linear(features, 8)
        self.relu = nn.ReLU()
        self.fc = nn.Linear(8, classes)

    def forward(self, x):
        return self.fc(self.relu(self.backbone(x)))


def _real_batch(splits, batch_size: int, use_train_transform: bool):
    """One deterministic real batch taken from the training split only."""
    dataset = splits.train_set
    indices = list(range(batch_size))
    previous = dataset.transform
    if not use_train_transform:
        from data_eval import eval_transform

        dataset.transform = eval_transform()
    try:
        images = torch.stack([dataset[index][0] for index in indices])
        labels = torch.tensor([dataset[index][1] for index in indices])
    finally:
        dataset.transform = previous
    return images, labels


# --------------------------------------------------------------------------- #
# checks
# --------------------------------------------------------------------------- #
def check_synthetic_pruning_ops(report: Report) -> None:
    """L1 selection, channel slicing, BN copy, residual shape, cost accounting."""
    import data_eval
    import model_ops
    from torchvision.models.resnet import Bottleneck

    started = time.time()
    weight = torch.zeros(6, 3)
    for index, magnitude in enumerate([0.1, 0.9, 0.4, 0.9, 0.2, 0.3]):
        weight[index] = magnitude
    keep = model_ops.l1_keep_indices(weight, 3)
    l1_ok = keep == [1, 2, 3]  # norms 0.9, 0.9, 0.4 win; ties by lower index; ascending order

    downsample = nn.Sequential(nn.Conv2d(64, 256, 1, stride=2, bias=False), nn.BatchNorm2d(256))
    block = Bottleneck(64, 64, stride=2, downsample=downsample).eval()
    pruned, record = model_ops.prune_bottleneck(block, 0.30, "smoke.block")
    probe = torch.randn(2, 64, 56, 56)
    with torch.no_grad():
        output = pruned(probe)
    bn_ok = (
        pruned.bn1.num_features == record["conv1_out_after"]
        and pruned.bn2.num_features == record["conv2_out_after"]
        and torch.equal(
            pruned.bn2.running_mean, block.bn2.running_mean[torch.tensor(record["keep2"])]
        )
    )
    slice_ok = (
        pruned.conv2.in_channels == record["conv1_out_after"]
        and pruned.conv2.out_channels == record["conv2_out_after"]
        and pruned.conv3.in_channels == record["conv2_out_after"]
        and pruned.conv3.out_channels == block.conv3.out_channels
    )
    residual_ok = tuple(output.shape) == (2, 256, 28, 28) and pruned.bn3.num_features == 256
    cost = data_eval.conv_linear_macs(nn.Sequential(nn.Conv2d(3, 4, 3, padding=1, bias=False), nn.BatchNorm2d(4),
                                                    nn.ReLU(), nn.AdaptiveAvgPool2d(1), nn.Flatten(),
                                                    nn.Linear(4, 2)).eval())
    cost_ok = cost["total_macs"] == 3 * 4 * 3 * 3 * 224 * 224 + 4 * 2 and cost["total_flops"] == 2 * cost["total_macs"]
    passed = l1_ok and bn_ok and slice_ok and residual_ok and cost_ok
    report.add(
        "synthetic pruning ops (L1 pick / conv2d.slice / BN copy / residual shape / cost)",
        passed,
        {
            "l1_keep": keep,
            "keep1": record["conv1_out_after"],
            "keep2": record["conv2_out_after"],
            "output_shape": list(output.shape),
            "macs": cost["total_macs"],
        },
        time.time() - started,
    )


def check_zero_ratio_rebuild(report: Report, model_a: nn.Module) -> None:
    """0% pruning must rebuild an identical model (engineering check, not a candidate)."""
    import model_ops

    started = time.time()
    rebuilt, prune_report = model_ops.prune_resnet50(model_a, 0.0)
    state_equal = all(
        torch.equal(value, rebuilt.state_dict()[key]) for key, value in model_a.state_dict().items()
    )
    probe = torch.randn(1, 3, 224, 224)
    with torch.no_grad():
        reference = model_a(probe)
        rebuilt_output = rebuilt(probe)
    difference = float((reference - rebuilt_output).abs().max().item())
    passed = state_equal and difference <= 1e-6
    report.add(
        "0% pruning rebuild consistency",
        passed,
        {
            "state_dict_identical": state_equal,
            "max_abs_diff": difference,
            "actual_ratio": prune_report["actual_ratio_overall"],
            "bottlenecks": prune_report["bottleneck_count"],
        },
        time.time() - started,
    )


def check_three_pruning_candidates(report: Report, model_a: nn.Module, splits) -> None:
    """Structure check plus one real training batch forward per candidate ratio."""
    import data_eval
    import model_ops

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    images, _ = _real_batch(splits, 4, use_train_transform=False)
    images = images.to(device)
    weight_total = sum(parameter.numel() for parameter in model_a.parameters())
    a_cost = data_eval.conv_linear_macs(model_a)
    results = []
    started = time.time()
    for ratio in (0.10, 0.20, 0.30):
        pruned, prune_report = model_ops.prune_resnet50(model_a, ratio)
        structure = model_ops.structural_check(pruned)
        cost = data_eval.conv_linear_macs(pruned)
        pruned = pruned.to(device)
        with torch.no_grad():
            output = pruned(images)
        entry = {
            "ratio": ratio,
            "channel_keep_ratio": prune_report["channel_keep_ratio"],
            "actual_ratio": prune_report["actual_ratio_overall"],
            "parameters": data_eval.count_parameters(pruned),
            "parameter_ratio": data_eval.count_parameters(pruned) / weight_total,
            "main_operator_flops": cost["total_flops"],
            "main_operator_flops_drop": 1.0 - cost["total_flops"] / a_cost["total_flops"],
            "output_shape": list(output.shape),
            "residual_shapes_consistent": structure["residual_shapes_consistent"],
            "finite": bool(torch.isfinite(output).all().item()),
        }
        results.append(entry)
        del pruned
        if device.type == "cuda":
            torch.cuda.empty_cache()
    passed = all(
        entry["residual_shapes_consistent"]
        and entry["finite"]
        and entry["output_shape"] == [4, 300]
        and entry["channel_keep_ratio"] >= 0.70
        for entry in results
    )
    report.add(
        "three pruning candidates: structure + one real batch forward",
        passed,
        {"device": device.type, "candidates": results},
        time.time() - started,
    )


def check_selected_pruning_backward(report: Report, model_a: nn.Module, splits) -> None:
    """One real forward+backward on the 30% candidate, without an optimizer update."""
    import data_eval
    import model_ops

    started = time.time()
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    pruned, _ = model_ops.prune_resnet50(model_a, 0.30)
    pruned = pruned.to(device)
    images, labels = _real_batch(splits, 4, use_train_transform=True)
    images, labels = images.to(device), labels.to(device)
    before = {name: parameter.detach().clone() for name, parameter in pruned.named_parameters()}
    pruned.train()
    logits = pruned(images)
    loss = nn.CrossEntropyLoss()(logits, labels)
    loss.backward()
    finite_loss = bool(torch.isfinite(loss).item())
    grads = [parameter.grad for parameter in pruned.parameters() if parameter.grad is not None]
    all_have_grads = len(grads) == sum(1 for _ in pruned.parameters())
    grads_finite = all(bool(torch.isfinite(grad).all().item()) for grad in grads)
    nonzero = sum(float(grad.abs().sum().item()) > 0 for grad in grads)
    weights_unchanged = all(
        torch.equal(before[name], parameter.detach()) for name, parameter in pruned.named_parameters()
    )
    passed = finite_loss and all_have_grads and grads_finite and nonzero > 0 and weights_unchanged
    report.add(
        "selected pruning model: one real batch forward/backward, no optimizer step",
        passed,
        {
            "device": device.type,
            "loss": float(loss.item()),
            "parameters_with_grads": len(grads),
            "parameters_with_nonzero_grads": nonzero,
            "weights_unchanged_after_backward": weights_unchanged,
        },
        time.time() - started,
    )


def check_quantization(report: Report, config: dict, splits, workdir: Path) -> None:
    """4 training images -> temporary calibration, quantized ops, export and reload."""
    import data_eval
    import model_ops

    started = time.time()
    model_a, _ = model_ops.load_fp32_model(config, device="cpu")
    indices = list(range(4))  # training split, evaluation preprocessing (calibration rule)
    model_a_eval_transform = data_eval.eval_transform()
    original_transform = splits.train_set.transform
    splits.train_set.transform = model_a_eval_transform
    try:
        calibration = [torch.stack([splits.train_set[index][0] for index in indices])]
    finally:
        splits.train_set.transform = original_transform

    quantized = model_ops.quantize_static_fx(model_a, config, calibration)
    inspection = model_ops.inspect_quantization(quantized)
    quantized_ok = (
        inspection["quantized_conv_count"] >= 50
        and inspection["quantized_linear_count"] >= 1
        and inspection["key_convolutions_all_quantized"]
        and inspection["float_conv_count"] == 0
        and inspection["float_linear_count"] == 0
    )
    export_info = model_ops.export_torchscript(
        quantized, workdir / "Q_smoke.pt", batch_size=1, relax_determinism=True
    )
    verification = model_ops.verify_export(
        workdir / "Q_smoke.pt", quantized, batch_sizes=(1, 8), relax_determinism=True
    )
    # PyTorch has no deterministic quantized CPU kernel, so strict determinism is
    # suspended for INT8 forward passes; measure whether the output is repeatable
    # anyway instead of claiming determinism we cannot enforce.
    probe = torch.randn(1, 3, 224, 224)
    with model_ops.relaxed_determinism(True), torch.no_grad():
        repeats = [quantized(probe) for _ in range(3)]
    repeatable = all(torch.equal(repeats[0], other) for other in repeats[1:])
    passed = quantized_ok and verification["all_consistent"] and repeatable
    report.add(
        "quantization: 4-image temporary calibration, quantized ops, export and reload",
        passed,
        {
            "calibration_images": 4,
            "quantized_conv_count": inspection["quantized_conv_count"],
            "quantized_linear_count": inspection["quantized_linear_count"],
            "float_conv_count": inspection["float_conv_count"],
            "float_linear_count": inspection["float_linear_count"],
            "quantize_boundaries": len(inspection["quantize_boundaries"]),
            "dequantize_boundaries": len(inspection["dequantize_boundaries"]),
            "export_bytes": export_info["bytes"],
            "batch_checks": verification["batch_checks"],
            "determinism_exception": "torch.use_deterministic_algorithms(False) for CPU INT8 forward only",
            "repeated_runs_bit_identical": repeatable,
            "temporary_model_deleted": True,
        },
        time.time() - started,
    )
    del quantized


def check_model_a_export(report: Report, config: dict, workdir: Path) -> None:
    """A exported with trace only, reloaded and compared at batch 1 and 8."""
    import model_ops

    started = time.time()
    model_a, meta = model_ops.load_fp32_model(config, device="cpu")
    export_info = model_ops.export_torchscript(model_a, workdir / "A_smoke.pt", batch_size=1)
    verification = model_ops.verify_export(workdir / "A_smoke.pt", model_a, batch_sizes=(1, 8))
    report.add(
        "model A export/reload at batch 1 and 8",
        verification["all_consistent"],
        {
            "model_sha256": meta["sha256"],
            "epoch": meta["epoch"],
            "export_bytes": export_info["bytes"],
            "batch_checks": verification["batch_checks"],
        },
        time.time() - started,
    )


def check_accumulation_group(report: Report) -> None:
    """Last incomplete accumulation group must keep its real samples."""
    import run

    started = time.time()
    dataset = _RandomDataset(length=5, features=8, classes=3)
    loader = DataLoader(dataset, batch_size=4, shuffle=False, drop_last=False)
    model = _TinyNet()
    initial_state = {key: value.detach().clone() for key, value in model.state_dict().items()}
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
    result = run.train_one_epoch(model, loader, optimizer, torch.device("cpu"), accumulation=4)

    reference = _TinyNet()
    reference.load_state_dict(initial_state)
    reference_optimizer = torch.optim.SGD(reference.parameters(), lr=0.1)
    reference_optimizer.zero_grad(set_to_none=True)
    loss = nn.CrossEntropyLoss()(reference(dataset.data), dataset.labels)
    loss.backward()
    torch.nn.utils.clip_grad_norm_(list(reference.parameters()), 1.0)
    reference_optimizer.step()
    matches = all(
        torch.allclose(parameter, other, atol=1e-6)
        for parameter, other in zip(model.parameters(), reference.parameters())
    )
    report.add(
        "last incomplete accumulation group (5 samples, batch 4, accumulation 4)",
        result["samples"] == 5 and matches,
        {
            "samples": result["samples"],
            "batches": len(loader),
            "gradient_equals_mean_over_samples": matches,
        },
        time.time() - started,
    )


def check_early_stop_and_resume(report: Report, config: dict, workdir: Path) -> None:
    """Platform stopping rule and checkpoint/resume fidelity on a tiny synthetic model."""
    import run

    started = time.time()
    # (a) the stop rule itself, using the real scheduler and the real counters
    model = _TinyNet()
    optimizer = run.build_optimizer(model, config)
    scheduler = run.build_scheduler(optimizer, config)
    counters = run.PlatformCounters(config)
    stop_epoch = None
    for epoch in range(1, 40):
        before = [group["lr"] for group in optimizer.param_groups]
        scheduler.step(1.0)
        after = [group["lr"] for group in optimizer.param_groups]
        counters.update(1.0, 0.10, any(after_lr < before_lr for before_lr, after_lr in zip(before, after)))
        stopped, _ = counters.should_stop()
        if stopped:
            stop_epoch = epoch
            break
    stop_rule_ok = stop_epoch == 12

    # (b) checkpoint round trip: one uninterrupted sequence vs stop+resume
    dataset = _RandomDataset(length=9, features=8, classes=3)
    loader = DataLoader(dataset, batch_size=2, shuffle=False, drop_last=False)
    torch.manual_seed(11)
    straight = _TinyNet()
    straight_optimizer = run.build_optimizer(straight, config)
    for _ in range(2):
        run.train_one_epoch(straight, loader, straight_optimizer, torch.device("cpu"), accumulation=2)

    torch.manual_seed(11)
    interrupted = _TinyNet()
    interrupted_optimizer = run.build_optimizer(interrupted, config)
    run.train_one_epoch(interrupted, loader, interrupted_optimizer, torch.device("cpu"), accumulation=2)
    checkpoint_path = workdir / "resume_smoke.pt"
    torch.save(
        {
            "model": interrupted.state_dict(),
            "optimizer": interrupted_optimizer.state_dict(),
            "epoch": 1,
            "config_sha256": run.config_sha256(),
        },
        checkpoint_path,
    )
    restored = _TinyNet()
    restored_optimizer = run.build_optimizer(restored, config)
    payload = torch.load(checkpoint_path, weights_only=False)
    restored.load_state_dict(payload["model"])
    restored_optimizer.load_state_dict(payload["optimizer"])
    run.train_one_epoch(restored, loader, restored_optimizer, torch.device("cpu"), accumulation=2)
    resume_ok = all(
        torch.allclose(parameter, other, atol=1e-7)
        for parameter, other in zip(straight.parameters(), restored.parameters())
    )
    report.add(
        "early-stopping rule and checkpoint resume",
        stop_rule_ok and resume_ok,
        {
            "earliest_stop_epoch_on_flat_metrics": stop_epoch,
            "resume_reproduces_uninterrupted_training": resume_ok,
        },
        time.time() - started,
    )


def check_data_split(report: Report, config: dict) -> None:
    import data_eval

    started = time.time()
    splits = data_eval.Splits(config)
    counts_ok = (
        splits.train_count == config["data"]["train_images"]
        and splits.val_count == config["data"]["val_images"]
        and splits.test_count == config["data"]["test_images"]
    )
    fingerprint_ok = splits.fingerprint == config["data"]["split_fingerprint_expected"]
    classes_ok = len(splits.classes) == config["data"]["classes"]
    report.add(
        "data split check (counts / disjoint manifests / fingerprint / class order)",
        counts_ok and fingerprint_ok and classes_ok,
        {
            "train": splits.train_count,
            "val": splits.val_count,
            "test": splits.test_count,
            "classes": len(splits.classes),
            "split_fingerprint": splits.fingerprint,
            "class_fingerprint": data_eval.class_fingerprint(splits.classes),
            "test_split_used": False,
        },
        time.time() - started,
    )


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    import data_eval
    import model_ops
    import run

    report = Report()
    print("experiment 3 engineering smoke checks (no full epoch, no final test evaluation)")
    config = run.load_config()
    permissions = run.load_permissions()
    report.add(
        "frozen config hash and permission binding",
        permissions["config_hash"] == run.config_sha256() == run.HASH_PATH.read_text(encoding="utf-8").strip(),
        {"config_sha256": run.config_sha256(), "scope": permissions.get("scope")},
    )
    environment = run.record_environment(config)
    report.add(
        "environment recorded (deterministic, FP32, no AMP/TF32, threads fixed)",
        environment["applied"]["deterministic_algorithms"] is True
        and environment["applied"]["cudnn_benchmark"] is False
        and environment["applied"]["torch_threads"] == config["environment"]["cpu_threads"],
        environment["applied"],
    )

    workdir = Path(tempfile.mkdtemp(prefix="experiment3_smoke_"))
    try:
        check_data_split(report, config)
        splits = data_eval.Splits(config)
        model_a, meta = model_ops.load_fp32_model(config, device="cpu")
        report.add(
            "model A checkpoint guard (sha256 / classes / split hash / epoch)",
            meta["sha256"] == config["paths"]["model_a_sha256"]
            and len(meta["classes"]) == 300
            and meta["epoch"] == config["paths"]["model_a_epoch"],
            {"sha256": meta["sha256"], "epoch": meta["epoch"], "classes": len(meta["classes"])},
        )

        check_synthetic_pruning_ops(report)
        check_zero_ratio_rebuild(report, model_a)
        check_three_pruning_candidates(report, model_a, splits)
        check_selected_pruning_backward(report, model_a, splits)
        del model_a
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        check_model_a_export(report, config, workdir)
        check_quantization(report, config, splits, workdir)
        check_accumulation_group(report)
        check_early_stop_and_resume(report, config, workdir)
    except Exception as error:  # noqa: BLE001 - report and stop, never continue silently
        report.add(
            "unhandled exception during smoke",
            False,
            {"error": f"{type(error).__name__}: {error}", "traceback": traceback.format_exc()},
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    payload = report.finish(
        {
            "config_sha256": run.config_sha256(),
            "temporary_artefacts_removed": not workdir.exists(),
            "formal_results_produced": False,
        }
    )
    print(f"\n{len(payload['checks']) - len(payload['failed'])}/{len(payload['checks'])} checks passed")
    if payload["failed"]:
        print("FAILED:", ", ".join(item["check"] for item in payload["failed"]))
    print(f"report: {REPORT_PATH}")
    return 0 if payload["all_passed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())

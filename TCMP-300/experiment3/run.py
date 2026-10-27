#!/usr/bin/env python
"""Experiment 3 entry point: INT8 static quantization and structured channel pruning.

Run without arguments to print help.  Every experiment parameter comes from the
frozen ``config.json``; the command line only selects a subcommand and, where
explicitly allowed, which already-enumerated model/device/batch combination to
measure.

Subcommands gated by ``execution_permissions.json`` refuse to run while the
corresponding permission is false, so receiving the plan is never treated as
authorization for a long task.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import subprocess
import sys
import time
from pathlib import Path

import torch
import torch.nn as nn

EXPERIMENT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = EXPERIMENT_DIR / "config.json"
HASH_PATH = EXPERIMENT_DIR / "config.sha256"
PERMISSIONS_PATH = EXPERIMENT_DIR / "execution_permissions.json"
RUNS_DIR = EXPERIMENT_DIR / "runs"


# --------------------------------------------------------------------------- #
# frozen config / permissions
# --------------------------------------------------------------------------- #
def config_sha256(path: Path = CONFIG_PATH) -> str:
    import hashlib

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_config(verify: bool = True) -> dict:
    if not CONFIG_PATH.is_file():
        raise SystemExit(f"missing frozen config: {CONFIG_PATH}")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if verify:
        recorded = HASH_PATH.read_text(encoding="utf-8").strip() if HASH_PATH.is_file() else ""
        actual = config_sha256()
        if recorded != actual:
            raise SystemExit(
                f"config.json changed: sha256 {actual} != frozen {recorded or '(missing)'}; "
                "refusing to run"
            )
    return config


def load_permissions() -> dict:
    if not PERMISSIONS_PATH.is_file():
        raise SystemExit(f"missing execution permissions: {PERMISSIONS_PATH}")
    permissions = json.loads(PERMISSIONS_PATH.read_text(encoding="utf-8"))
    expected = permissions.get("config_hash")
    actual = config_sha256()
    if expected != actual:
        raise SystemExit(
            f"execution_permissions.json is bound to config {expected} but config is {actual}; "
            "refusing to run"
        )
    return permissions


def require(permission: str) -> dict:
    permissions = load_permissions()
    allowed = permissions.get("permissions", {}).get(permission, False)
    if not allowed:
        raise SystemExit(
            f"permission '{permission}' is false in execution_permissions.json; "
            "this stage is not authorized in the current scope. Stopping without running anything."
        )
    return permissions


def write_json(path: Path, payload) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def ensure_runs_dir() -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    return RUNS_DIR


# --------------------------------------------------------------------------- #
# environment
# --------------------------------------------------------------------------- #
def record_environment(config: dict) -> dict:
    import data_eval

    applied = data_eval.configure_determinism(config)
    device = torch.device(config["environment"]["device_train"])
    payload = {
        "applied": applied,
        "versions": data_eval.software_versions(device if torch.cuda.is_available() else torch.device("cpu")),
        "config_sha256": config_sha256(),
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    write_json(ensure_runs_dir() / "environment.json", payload)
    return payload


def device_of(spec: str) -> torch.device:
    device = torch.device(spec)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise SystemExit("CUDA device requested but not available")
    return device


# --------------------------------------------------------------------------- #
# config-check
# --------------------------------------------------------------------------- #
def cmd_config_check(args) -> int:
    config = load_config()
    permissions = load_permissions()
    summary = {
        "config_sha256": config_sha256(),
        "config_bytes": CONFIG_PATH.stat().st_size,
        "authorized_stages": config["scope_authorization"]["authorized_stages"],
        "permissions": permissions["permissions"],
        "paths": config["paths"],
        "data": {key: config["data"][key] for key in ("classes", "train_images", "val_images", "test_images")},
        "quantization": {
            "engine": config["quantization"]["engine"],
            "activation": f"{config['quantization']['activation_dtype']} {config['quantization']['activation_qscheme']} "
            f"[{config['quantization']['activation_quant_min']}, {config['quantization']['activation_quant_max']}]",
            "weight": f"{config['quantization']['weight_dtype']} {config['quantization']['weight_qscheme']} axis="
            f"{config['quantization']['weight_ch_axis']}",
        },
        "pruning": {"ratios": config["pruning"]["ratios"], "keep_formula": config["pruning"]["keep_channels_formula"]},
        "finetune": {
            "physical_batch": config["finetune"]["physical_batch"],
            "accumulation": config["finetune"]["grad_accumulation"],
            "stop_conditions": config["finetune"]["stop_conditions_all_required"],
        },
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


# --------------------------------------------------------------------------- #
# audit / baselines
# --------------------------------------------------------------------------- #
def cmd_audit(args) -> int:
    """Full data fingerprint audit: hash and decode every image file (step 4)."""
    require("full_data_audit")
    import data_eval

    config = load_config()
    record_environment(config)
    paths = config["paths"]
    splits = data_eval.Splits(config)

    directory_audit: list[dict] = []
    for split_name, directory in (("train", paths["train_dir"]), ("val", paths["val_dir"])):
        root = Path(directory)
        files = sorted(path for path in root.rglob("*") if path.is_file())
        entries: list[dict] = []
        decode_failures: list[str] = []
        for index, path in enumerate(files, 1):
            relative = path.resolve().relative_to(root.resolve()).as_posix()
            try:
                from PIL import Image

                with Image.open(path) as image:
                    image.convert("RGB").load()
            except Exception as error:  # noqa: BLE001 - recorded, then reported
                decode_failures.append(f"{relative}: {type(error).__name__}")
            entries.append(
                {
                    "relative_path": relative,
                    "bytes": int(path.stat().st_size),
                    "sha256": data_eval.file_sha256(path),
                }
            )
            if index % 5000 == 0:
                print(f"  {split_name}: hashed {index}/{len(files)}", flush=True)
        directory_audit.append(
            {
                "split": split_name,
                "directory": str(root),
                "file_count": len(files),
                "total_bytes": int(sum(entry["bytes"] for entry in entries)),
                "directory_sha256": data_eval.hashlib.sha256(
                    ("\n".join(f"{entry['relative_path']} {entry['sha256']}" for entry in entries) + "\n").encode()
                ).hexdigest(),
                "decode_failures": decode_failures,
                "files": entries,
            }
        )

    payload = {
        "config_sha256": config_sha256(),
        "split_fingerprint": splits.fingerprint,
        "class_fingerprint": data_eval.class_fingerprint(splits.classes),
        "classes": splits.classes,
        "class_counts": {
            "train": [int(count) for count in _class_counts(splits.train_set)],
            "val": [int(count) for count in _class_counts(splits.full_val_set)],
        },
        "splits": {
            "train": splits.train_count,
            "val": splits.val_count,
            "test": splits.test_count,
        },
        "directories": directory_audit,
    }
    path = write_json(ensure_runs_dir() / "data_audit.json", payload)
    failures = sum(len(entry["decode_failures"]) for entry in directory_audit)
    print(f"data audit written to {path}; decode failures: {failures}")
    return 0 if failures == 0 else 3


def _class_counts(image_folder) -> list[int]:
    counts = [0] * len(image_folder.classes)
    for _, label in image_folder.samples:
        counts[label] += 1
    return counts


def cmd_baseline(args) -> int:
    """Measure A on the validation split (step 4)."""
    require("baseline_validation")
    import data_eval
    import model_ops

    config = load_config()
    record_environment(config)
    splits = data_eval.Splits(config)
    model, meta = model_ops.load_fp32_model(config, device="cpu")
    results = {"model": meta, "split_fingerprint": splits.fingerprint}
    for spec in (config["environment"]["device_quant_cpu_eval"], config["environment"]["device_train"]):
        device = device_of(spec)
        model.to(device)
        loader = data_eval.make_eval_loader(
            splits.val_set,
            config["finetune"]["val_batch"],
            workers=int(config["evaluation"]["dataloader_workers"]),
        )
        started = time.time()
        metrics = data_eval.evaluate(model, loader, device)
        metrics["seconds"] = time.time() - started
        metrics["device"] = spec
        results[spec] = {key: value for key, value in metrics.items() if not hasattr(value, "shape")}
        print(f"A on {spec}: top1={metrics['top1']:.6f} top5={metrics['top5']:.6f} ce={metrics['ce']:.6f}")
    write_json(ensure_runs_dir() / "baseline" / "a_validation.json", results)
    return 0


# --------------------------------------------------------------------------- #
# quantization
# --------------------------------------------------------------------------- #
def _calibration_batches(dataset, indices: list[int], batch_size: int) -> list[torch.Tensor]:
    images = [dataset[index][0] for index in indices]
    batches = []
    for start in range(0, len(images), batch_size):
        batches.append(torch.stack(images[start : start + batch_size]))
    return batches


def cmd_quantize(args) -> int:
    """Calibration tiers 600 / 1500 / 3000 and validation-based selection (step 5)."""
    require("quantization_selection")
    import data_eval
    import model_ops

    config = load_config()
    record_environment(config)
    splits = data_eval.Splits(config)
    run_dir = ensure_runs_dir() / "quantization"
    run_dir.mkdir(parents=True, exist_ok=True)

    baseline_path = ensure_runs_dir() / "baseline" / "a_validation.json"
    if not baseline_path.is_file():
        raise SystemExit("missing runs/baseline/a_validation.json - run 'baseline' first")
    baseline = read_json(baseline_path)
    cpu = config["environment"]["device_quant_cpu_eval"]
    a_top1 = float(baseline[cpu]["top1"])
    a_ce = float(baseline[cpu]["ce"])
    a_top5 = float(baseline[cpu]["top5"])
    print(f"A CPU validation: top1={a_top1:.6f} top5={a_top5:.6f} ce={a_ce:.6f}")

    val_loader = data_eval.make_eval_loader(
        splits.val_set,
        config["finetune"]["val_batch"],
        workers=int(config["evaluation"]["dataloader_workers"]),
    )
    allowed_drop = float(config["targets"]["quantization"].get("top1_drop_max_percentage_points", 2.0)) / 100.0

    candidates: list[dict] = []
    # FX GraphModules cannot be pickled reliably (torch.save/torch.load loses the
    # quantized module attributes), so every built candidate is kept in memory
    # instead and Q is rebuilt from A + the recorded calibration set when needed.
    built: dict[int, object] = {}
    selected = None
    for per_class in config["calibration"]["tiers_per_class"]:
        indices, rows = data_eval.calibration_indices(splits.train_set, per_class)
        manifest_path = run_dir / f"calibration_{len(indices)}_manifest.json"
        data_eval.calibration_manifest(splits.train_set, indices, manifest_path)

        model = model_ops.load_fp32_model(config, device="cpu")[0]
        batches = _calibration_batches(splits.train_set, indices, config["calibration"]["batch_size"])
        quantized = model_ops.quantize_static_fx(model, config, batches)
        inspection = model_ops.inspect_quantization(quantized)
        write_json(run_dir / f"inspection_{len(indices)}.json", inspection)

        started = time.time()
        metrics = data_eval.evaluate(
            quantized, val_loader, torch.device("cpu"), relax_determinism=True
        )
        seconds = time.time() - started
        candidate = {
            "calibration_per_class": per_class,
            "calibration_images": len(indices),
            "calibration_manifest": str(manifest_path),
            "val_top1": float(metrics["top1"]),
            "val_top5": float(metrics["top5"]),
            "val_ce": float(metrics["ce"]),
            "top1_drop": float(a_top1 - metrics["top1"]),
            "meets_target": bool(a_top1 - metrics["top1"] <= allowed_drop + 1e-12),
            "key_convolutions_quantized": inspection["key_convolutions_all_quantized"],
            "quantized_conv_count": inspection["quantized_conv_count"],
            "quantized_linear_count": inspection["quantized_linear_count"],
            "eval_seconds": seconds,
        }
        candidates.append(candidate)
        print(
            f"tier {len(indices)}: top1={candidate['val_top1']:.6f} drop={candidate['top1_drop']*100:+.3f}pp "
            f"target={'MET' if candidate['meets_target'] else 'missed'}"
        )
        write_json(run_dir / "candidates.json", {"baseline": {"top1": a_top1, "top5": a_top5, "ce": a_ce},
                                                 "candidates": candidates})
        built[candidate["calibration_images"]] = quantized
        if candidate["meets_target"]:
            selected = candidate
            selected_module = quantized
            break

    if selected is None:
        ranked = sorted(
            candidates,
            key=lambda item: (-item["val_top1"], item["val_ce"], item["calibration_images"]),
        )
        selected = ranked[0]
        selected_module = built[selected["calibration_images"]]
        selected["target_met"] = False
    else:
        selected["target_met"] = True

    selection = {
        "baseline_cpu": {"top1": a_top1, "top5": a_top5, "ce": a_ce},
        "allowed_top1_drop": allowed_drop,
        "candidates": candidates,
        "selected": {
            "calibration_per_class": selected["calibration_per_class"],
            "calibration_images": selected["calibration_images"],
            "calibration_manifest": selected["calibration_manifest"],
            "val_top1": selected["val_top1"],
            "val_ce": selected["val_ce"],
            "top1_drop": selected["top1_drop"],
            "target_met": selected["target_met"],
        },
        "note": "Q and P both start independently from A; no joint pruning+quantization model is built.",
        "rebuild_rule": (
            "The FX GraphModule is not pickled. Q is rebuilt deterministically from A by "
            "re-running calibration with selected.calibration_per_class images per class "
            "(same seed, same nested calibration set) whenever a later stage needs it."
        ),
    }
    write_json(run_dir / "selection.json", selection)
    print(f"selected tier {selected['calibration_images']}: top1={selected['val_top1']:.6f} "
          f"drop={selected['top1_drop']*100:+.3f}pp target_met={selected['target_met']}", flush=True)
    if not selected["target_met"]:
        print(
            "WARNING: none of the calibration tiers met the <=2 percentage-point target; "
            "the best validation tier is selected and the miss is reported, as the plan requires.",
            flush=True,
        )
    return 0


# --------------------------------------------------------------------------- #
# pruning
# --------------------------------------------------------------------------- #
def cmd_prune_screen(args) -> int:
    """Build three independent candidates, screen them, pick the one to fine-tune (step 6)."""
    require("pruning_screening")
    import data_eval
    import model_ops

    config = load_config()
    record_environment(config)
    splits = data_eval.Splits(config)
    run_dir = ensure_runs_dir() / "pruning"
    run_dir.mkdir(parents=True, exist_ok=True)
    device = device_of(config["environment"]["device_train"])
    val_loader = data_eval.make_eval_loader(
        splits.val_set,
        config["finetune"]["val_batch"],
        workers=int(config["evaluation"]["dataloader_workers"]),
    )

    baseline_path = ensure_runs_dir() / "baseline" / "a_validation.json"
    if not baseline_path.is_file():
        raise SystemExit("missing runs/baseline/a_validation.json - run 'baseline' first")
    baseline = read_json(baseline_path)
    a_top1 = float(baseline[config["environment"]["device_train"]]["top1"])

    fp32_model, a_meta = model_ops.load_fp32_model(config, device="cpu")
    a_cost = data_eval.conv_linear_macs(fp32_model)
    a_params = data_eval.count_parameters(fp32_model)
    candidates: list[dict] = []
    for ratio in config["pruning"]["ratios"]:
        pruned, report = model_ops.prune_resnet50(fp32_model, ratio)
        structure = model_ops.structural_check(pruned)
        if not structure["residual_shapes_consistent"]:
            raise RuntimeError(f"candidate {ratio}: residual shapes inconsistent - stopping")
        cost = data_eval.conv_linear_macs(pruned)
        params = data_eval.count_parameters(pruned)
        pruned = pruned.to(device)
        metrics = data_eval.evaluate(pruned, val_loader, device)
        flops_drop = 1.0 - cost["total_flops"] / a_cost["total_flops"]
        candidate = {
            "requested_ratio": float(ratio),
            "channel_keep_ratio": float(report["channel_keep_ratio"]),
            "actual_ratio_overall": float(report["actual_ratio_overall"]),
            "parameters": int(params),
            "parameter_ratio": float(params / a_params),
            "main_operator_macs": int(cost["total_macs"]),
            "main_operator_flops": int(cost["total_flops"]),
            "main_operator_flops_drop": float(flops_drop),
            "flops_target_met": bool(flops_drop >= 0.30 - 1e-12),
            "val_top1": float(metrics["top1"]),
            "val_top5": float(metrics["top5"]),
            "val_ce": float(metrics["ce"]),
            "top1_drop": float(a_top1 - metrics["top1"]),
            "structure": {key: value for key, value in structure.items() if key != "blocks"},
            "blocks": report["blocks"],
            "blocks_detail": structure.get("blocks", []),
        }
        candidates.append(candidate)
        write_json(run_dir / f"candidate_{int(ratio * 100)}.json", candidate)
        print(
            f"ratio {ratio:.2f}: keep={candidate['channel_keep_ratio']:.4f} "
            f"flops_drop={flops_drop*100:.2f}% top1={candidate['val_top1']:.6f} "
            f"drop={candidate['top1_drop']*100:+.3f}pp"
        )
        # keep the initialised weights of every candidate for the record
        torch.save({"model": pruned.state_dict(), "ratio": float(ratio), "report": report},
                   run_dir / f"P_init_{int(ratio * 100)}.pt")

    qualified = [item for item in candidates if item["flops_target_met"]]
    if qualified:
        selected = sorted(qualified, key=lambda item: (-item["val_top1"], item["val_ce"], item["requested_ratio"]))[0]
        target_met = True
    else:
        selected = next(item for item in candidates if abs(item["requested_ratio"] - 0.30) < 1e-12)
        target_met = False
    screening = {
        "model_a": a_meta,
        "a_validation_top1": a_top1,
        "a_parameters": int(a_params),
        "a_main_operator_macs": int(a_cost["total_macs"]),
        "a_main_operator_flops": int(a_cost["total_flops"]),
        "flops_scope": "Conv2d + Linear only, 1 MAC = 2 FLOPs; BN/activation/pooling/residual add excluded",
        "candidates": candidates,
        "selected_ratio": float(selected["requested_ratio"]),
        "flops_target_met": target_met,
        "selection_rule": config["pruning"]["selection_rule"],
        "claim_note": "selected from the un-fine-tuned validation result only; this is not the optimal pruning rate after fine-tuning",
    }
    write_json(run_dir / "screening.json", screening)
    print(f"selected ratio {selected['requested_ratio']:.2f} (flops target met: {target_met})")
    return 0


# --------------------------------------------------------------------------- #
# fine-tune
# --------------------------------------------------------------------------- #
def build_optimizer(model: nn.Module, config: dict) -> torch.optim.Optimizer:
    ft = config["finetune"]
    backbone, head = [], []
    for name, parameter in model.named_parameters():
        (head if name.startswith("fc.") else backbone).append(parameter)
    optimizer = torch.optim.AdamW(
        [
            {"params": backbone, "lr": float(ft["backbone_lr"])},
            {"params": head, "lr": float(ft["head_lr"])},
        ],
        betas=tuple(float(value) for value in ft["betas"]),
        eps=float(ft["eps"]),
        weight_decay=float(ft["weight_decay"]),
        amsgrad=bool(ft["amsgrad"]),
    )
    return optimizer


def build_scheduler(optimizer: torch.optim.Optimizer, config: dict) -> torch.optim.lr_scheduler.ReduceLROnPlateau:
    scheduler = config["finetune"]["scheduler"]
    return torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer,
        mode=scheduler["mode"],
        factor=float(scheduler["factor"]),
        patience=int(scheduler["patience"]),
        threshold=float(scheduler["threshold"]),
        threshold_mode=scheduler["threshold_mode"],
        cooldown=int(scheduler["cooldown"]),
        min_lr=[float(scheduler["min_lr_backbone"]), float(scheduler["min_lr_head"])],
        eps=float(scheduler["eps"]),
    )


def train_one_epoch(model, loader, optimizer, device, accumulation: int) -> dict:
    """One epoch with gradient accumulation.

    The last physical batch is kept and the final accumulation group uses its
    real number of samples: every physical batch is scaled by
    ``batch_samples / group_samples`` so the accumulated gradient is exactly the
    mean over the samples of that group (no padding, no dropped remainder).
    """
    model.train()
    criterion = nn.CrossEntropyLoss()
    parameters = [parameter for parameter in model.parameters() if parameter.requires_grad]
    total_batches = len(loader)
    batch_size = int(loader.batch_size)
    group_size = int(accumulation)
    total_samples = len(loader.dataset)
    last_batch_size = total_samples - batch_size * (total_batches - 1)

    def samples_in_batch(batch_index: int) -> int:
        return batch_size if batch_index < total_batches - 1 else last_batch_size

    # sample count of every accumulation group, known analytically from the loader
    group_samples: list[int] = []
    for group_start in range(0, total_batches, group_size):
        group_end = min(group_start + group_size, total_batches)
        group_samples.append(sum(samples_in_batch(i) for i in range(group_start, group_end)))

    optimizer.zero_grad(set_to_none=True)
    total_loss = 0.0
    correct = 0
    seen = 0
    for step, (images, labels) in enumerate(loader, 1):
        images = images.to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)
        logits = model(images)
        loss = criterion(logits, labels)
        if not torch.isfinite(loss):
            raise RuntimeError(f"non-finite loss at batch {step} - stopping as required")
        batch_index = step - 1
        group_index = batch_index // group_size
        weight = samples_in_batch(batch_index) / group_samples[group_index]
        (loss * weight).backward()
        if step % group_size == 0 or step == total_batches:
            torch.nn.utils.clip_grad_norm_(parameters, 1.0)
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
        total_loss += float(loss.item()) * int(labels.size(0))
        correct += int((logits.argmax(dim=1) == labels).sum().item())
        seen += int(labels.size(0))
        if step % 500 == 0 or step == total_batches:
            print(f"  batch {step}/{total_batches} loss={total_loss / seen:.4f} acc={correct / seen:.2%}", flush=True)
    return {"loss": total_loss / seen, "accuracy": correct / seen, "samples": seen}


def _rng_state(generator: torch.Generator | None) -> dict:
    state = {"python": random.getstate(), "torch": torch.get_rng_state()}
    if torch.cuda.is_available():
        state["cuda"] = torch.cuda.get_rng_state_all()
    if generator is not None:
        state["loader_generator"] = generator.get_state()
    return state


def _restore_rng_state(state: dict, generator: torch.Generator | None) -> None:
    random.setstate(state["python"])
    torch.set_rng_state(state["torch"])
    if state.get("cuda") and torch.cuda.is_available():
        torch.cuda.set_rng_state_all(state["cuda"])
    if generator is not None and "loader_generator" in state:
        generator.set_state(state["loader_generator"])


class PlatformCounters:
    """The validation platform that decides when to stop (never a fixed epoch count).

    Every threshold comes from ``config["finetune"]["stop_params"]`` so a rule
    change is visible in the frozen config instead of being hidden in code.
    """

    def __init__(self, config: dict):
        ft = config["finetune"]
        params = ft.get("stop_params", {})
        self.min_epochs = int(params.get("min_epochs", 5))
        self.ce_patience = int(params.get("ce_patience", 8))
        self.top1_patience = int(params.get("top1_patience", 8))
        self.ce_threshold = float(params.get("ce_threshold", 0.001))  # 0.1% relative
        self.top1_threshold = float(params.get("top1_threshold", 0.001))  # 0.1 percentage point
        self.min_lr_reductions = int(params.get("min_lr_reductions", 2))
        self.min_epochs_after_reduction = int(params.get("min_epochs_after_reduction", 3))
        self.best_ce = float("inf")
        self.best_top1 = -1.0
        self.ce_stale = 0
        self.top1_stale = 0
        self.lr_reductions = 0
        self.epochs_since_reduction = 0
        self.epoch = 0

    def update(self, val_ce: float, val_top1: float, lr_reduced: bool) -> dict:
        self.epoch += 1
        if self.best_ce == float("inf") or val_ce < self.best_ce * (1.0 - self.ce_threshold):
            if val_ce < self.best_ce:
                self.best_ce = val_ce
            self.ce_stale = 0
        else:
            self.ce_stale += 1
        if val_top1 > self.best_top1 + self.top1_threshold:
            self.best_top1 = val_top1
            self.top1_stale = 0
        else:
            self.best_top1 = max(self.best_top1, val_top1)
            self.top1_stale += 1
        if lr_reduced:
            self.lr_reductions += 1
            self.epochs_since_reduction = 0
        else:
            self.epochs_since_reduction += 1
        return self.state()

    def state(self) -> dict:
        return {
            "epoch": self.epoch,
            "best_ce": self.best_ce,
            "best_top1": self.best_top1,
            "ce_stale": self.ce_stale,
            "top1_stale": self.top1_stale,
            "lr_reductions": self.lr_reductions,
            "epochs_since_reduction": self.epochs_since_reduction,
        }

    def should_stop(self) -> tuple[bool, list[dict]]:
        checks = [
            {"condition": f"epochs >= {self.min_epochs}", "value": self.epoch,
             "met": self.epoch >= self.min_epochs},
            {"condition": f"val CE stale >= {self.ce_patience}", "value": self.ce_stale,
             "met": self.ce_stale >= self.ce_patience},
            {"condition": f"val Top-1 stale >= {self.top1_patience}", "value": self.top1_stale,
             "met": self.top1_stale >= self.top1_patience},
            {"condition": f"lr reductions >= {self.min_lr_reductions}", "value": self.lr_reductions,
             "met": self.lr_reductions >= self.min_lr_reductions},
            {
                "condition": f"epochs since last reduction >= {self.min_epochs_after_reduction}",
                "value": self.epochs_since_reduction,
                "met": self.epochs_since_reduction >= self.min_epochs_after_reduction,
            },
        ]
        return all(check["met"] for check in checks), checks


def cmd_finetune(args) -> int:
    """Fine-tune the single selected pruned model until the validation platform stops (step 7)."""
    require("full_training")
    import data_eval
    import model_ops

    config = load_config()
    record_environment(config)
    splits = data_eval.Splits(config)

    screening_path = ensure_runs_dir() / "pruning" / "screening.json"
    if not screening_path.is_file():
        raise SystemExit("missing runs/pruning/screening.json - run 'prune-screen' first")
    screening = read_json(screening_path)
    ratio = float(screening["selected_ratio"])
    run_dir = ensure_runs_dir() / "finetune"
    run_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = run_dir / "metrics.csv"
    last_path = run_dir / "checkpoint_last.pt"
    prev_path = run_dir / "checkpoint_prev.pt"

    ft = config["finetune"]
    device = device_of(config["environment"]["device_train"])

    # reset the seed right before fine-tuning so candidate construction does not shift it
    import numpy as np

    random.seed(ft["seed_reset"])
    np.random.seed(ft["seed_reset"])
    torch.manual_seed(ft["seed_reset"])
    torch.cuda.manual_seed_all(ft["seed_reset"])

    fp32_model = model_ops.load_fp32_model(config, device="cpu")[0]
    if args.resume:
        checkpoint = torch.load(last_path, map_location="cpu", weights_only=False)
        if checkpoint.get("config_sha256") != config_sha256():
            raise SystemExit("checkpoint belongs to a different config - refusing silent resume")
        if checkpoint.get("software_versions") != data_eval.software_versions(device):
            raise SystemExit("software changed since the checkpoint - refusing silent resume")
        pruned, report = model_ops.prune_resnet50(fp32_model, float(checkpoint["ratio"]))
        model = pruned.to(device)
        model.load_state_dict(checkpoint["model"])
        optimizer = build_optimizer(model, config)
        optimizer.load_state_dict(checkpoint["optimizer"])
        scheduler = build_scheduler(optimizer, config)
        scheduler.load_state_dict(checkpoint["scheduler"])
        counters = PlatformCounters(config)
        counters.__dict__.update(checkpoint["counters"])
        best = checkpoint["best"]
        start_epoch = int(checkpoint["epoch"]) + 1
        _restore_rng_state(checkpoint["rng"], None)
        print(f"resuming from epoch {start_epoch} (best top1={best['val_top1']:.6f})")
    else:
        pruned, report = model_ops.prune_resnet50(fp32_model, ratio)
        model = pruned.to(device)
        optimizer = build_optimizer(model, config)
        scheduler = build_scheduler(optimizer, config)
        counters = PlatformCounters(config)
        best = {"epoch": 0, "val_top1": -1.0, "val_ce": float("inf"), "state": None}
        start_epoch = 1
        with metrics_path.open("w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerow(
                ["epoch", "train_loss", "train_accuracy", "val_ce", "val_top1", "val_top5", "lr_backbone", "lr_head"]
            )

    loader, dataset = data_eval.make_train_loader(
        splits.train_set,
        physical_batch=int(ft["physical_batch"]),
        workers=int(ft["dataloader"]["workers"]),
        seed=int(ft["seed_reset"]),
        epoch=start_epoch,
    )
    val_loader = data_eval.make_eval_loader(
        splits.val_set, int(ft["val_batch"]), workers=int(config["evaluation"]["dataloader_workers"])
    )
    generator = loader.sampler.generator
    accumulation = int(ft["grad_accumulation"])
    epoch = start_epoch
    try:
        while True:
            dataset.set_epoch(epoch)
            lr_before = [group["lr"] for group in optimizer.param_groups]
            print(f"epoch {epoch} lr={lr_before}", flush=True)
            # approved speed-up option B: non-deterministic kernels are allowed for
            # the training pass only; validation below runs with determinism restored
            with model_ops.relaxed_determinism(True):
                train_metrics = train_one_epoch(model, loader, optimizer, device, accumulation)
            val = data_eval.evaluate(model, val_loader, device)
            scheduler.step(float(val["ce"]))
            lr_after = [group["lr"] for group in optimizer.param_groups]
            lr_reduced = any(after < before for before, after in zip(lr_before, lr_after))
            state = counters.update(float(val["ce"]), float(val["top1"]), lr_reduced)
            with metrics_path.open("a", newline="", encoding="utf-8") as handle:
                csv.writer(handle).writerow(
                    [
                        epoch,
                        f"{train_metrics['loss']:.6f}",
                        f"{train_metrics['accuracy']:.6f}",
                        f"{val['ce']:.6f}",
                        f"{val['top1']:.6f}",
                        f"{val['top5']:.6f}",
                        f"{lr_after[0]:.10g}",
                        f"{lr_after[1]:.10g}",
                    ]
                )
            better = (
                val["top1"] > best["val_top1"] + 1e-12
                or (abs(val["top1"] - best["val_top1"]) <= 1e-12 and val["ce"] < best["val_ce"] - 1e-12)
            )
            if better:
                best = {
                    "epoch": epoch,
                    "val_top1": float(val["top1"]),
                    "val_ce": float(val["ce"]),
                    "state": {key: value.detach().cpu().clone() for key, value in model.state_dict().items()},
                }
            payload = {
                "model": model.state_dict(),
                "optimizer": optimizer.state_dict(),
                "scheduler": scheduler.state_dict(),
                "epoch": epoch,
                "ratio": ratio,
                "prune_report": report,
                "counters": state,
                "best": {key: best[key] for key in ("epoch", "val_top1", "val_ce")},
                "rng": _rng_state(generator),
                "config_sha256": config_sha256(),
                "software_versions": data_eval.software_versions(device),
                "classes": splits.classes,
                "split_fingerprint": splits.fingerprint,
                "training_determinism_relaxed": True,
                "speedup_option": "B",
            }
            if last_path.is_file():
                os.replace(last_path, prev_path)
            torch.save(payload, last_path)
            print(
                f"epoch {epoch}: train {train_metrics['accuracy']:.2%} val top1={val['top1']:.4%} ce={val['ce']:.4f} "
                f"lr_reduced={lr_reduced} ce_stale={state['ce_stale']} top1_stale={state['top1_stale']} "
                f"reductions={state['lr_reductions']}",
                flush=True,
            )
            stopped, checks = counters.should_stop()
            write_json(run_dir / "platform_state.json", {"epoch": epoch, "counters": state, "checks": checks,
                                                        "stop": stopped, "best": payload["best"]})
            if stopped:
                print(f"validation platform stopped at epoch {epoch}")
                break
            epoch += 1
    finally:
        if best["state"] is not None:
            torch.save(
                {
                    "model": best["state"],
                    "ratio": ratio,
                    "prune_report": report,
                    "best": {key: best[key] for key in ("epoch", "val_top1", "val_ce")},
                    "classes": splits.classes,
                    "split_fingerprint": splits.fingerprint,
                    "config_sha256": config_sha256(),
                },
                run_dir / "best.pt",
            )
            print(f"best epoch {best['epoch']}: top1={best['val_top1']:.6f} ce={best['val_ce']:.6f}")
    return 0


# --------------------------------------------------------------------------- #
# freeze / evaluate / benchmark
# --------------------------------------------------------------------------- #
def load_frozen_model(config: dict, name: str) -> nn.Module:
    import model_ops

    path = ensure_runs_dir() / "frozen" / f"{name}.pt"
    if not path.is_file():
        raise SystemExit(f"missing frozen model {path} - run 'freeze' first")
    return model_ops._load_torchscript(path)


def cmd_freeze(args) -> int:
    """Export A, Q and P with trace only, then re-load and cross-check (step 8)."""
    require("freeze_models")
    import data_eval
    import model_ops

    config = load_config()
    record_environment(config)
    run_dir = ensure_runs_dir() / "frozen"
    run_dir.mkdir(parents=True, exist_ok=True)
    report: dict = {"config_sha256": config_sha256(), "exports": {}, "verify": {}}

    # A
    model_a, meta_a = model_ops.load_fp32_model(config, device="cpu")
    report["exports"]["A"] = model_ops.export_torchscript(model_a, run_dir / "A.pt")
    report["verify"]["A"] = model_ops.verify_export(run_dir / "A.pt", model_a)

    # Q: rebuilt deterministically from A, because an FX GraphModule cannot be
    # pickled; the calibration recipe comes from runs/quantization/selection.json
    selection_path = ensure_runs_dir() / "quantization" / "selection.json"
    if not selection_path.is_file():
        raise SystemExit("missing runs/quantization/selection.json - run 'quantize' first")
    selection = read_json(selection_path)
    per_class = int(selection["selected"]["calibration_per_class"])
    splits = data_eval.Splits(config)
    indices, _ = data_eval.calibration_indices(splits.train_set, per_class)
    if len(indices) != int(selection["selected"]["calibration_images"]):
        raise SystemExit("rebuilt calibration set size does not match the recorded selection - stopping")
    batches = _calibration_batches(splits.train_set, indices, int(config["calibration"]["batch_size"]))
    model_q = model_ops.quantize_static_fx(model_ops.load_fp32_model(config, device="cpu")[0], config, batches)
    report["q_rebuild"] = {"calibration_per_class": per_class, "calibration_images": len(indices)}
    report["exports"]["Q"] = model_ops.export_torchscript(
        model_q, run_dir / "Q.pt", relax_determinism=True
    )
    report["verify"]["Q"] = model_ops.verify_export(
        run_dir / "Q.pt", model_q, relax_determinism=True
    )

    # P
    best_path = ensure_runs_dir() / "finetune" / "best.pt"
    if not best_path.is_file():
        raise SystemExit("missing runs/finetune/best.pt - run 'finetune' first")
    best = torch.load(best_path, map_location="cpu", weights_only=False)
    model_p, _ = model_ops.prune_resnet50(model_ops.load_fp32_model(config, device="cpu")[0], float(best["ratio"]))
    model_p.load_state_dict(best["model"])
    model_p.eval()
    report["exports"]["P"] = model_ops.export_torchscript(model_p, run_dir / "P.pt")
    report["verify"]["P"] = model_ops.verify_export(run_dir / "P.pt", model_p)

    report["sizes"] = {
        name: Path(item["path"]).stat().st_size for name, item in report["exports"].items()
    }
    report["all_verified"] = all(item["all_consistent"] for item in report["verify"].values())
    write_json(run_dir / "freeze_report.json", report)
    print(json.dumps({"sizes": report["sizes"], "all_verified": report["all_verified"]}, indent=2))
    return 0 if report["all_verified"] else 3


def cmd_evaluate(args) -> int:
    """One final evaluation per frozen model/device pair on the full test split (step 9)."""
    require("final_evaluation")
    import data_eval
    import numpy as np

    config = load_config()
    record_environment(config)
    splits = data_eval.Splits(config)
    run_dir = ensure_runs_dir() / "evaluation"
    run_dir.mkdir(parents=True, exist_ok=True)
    labelled = data_eval.IndexedDataset(splits.test_set)
    loader = data_eval.make_eval_loader(
        labelled,
        batch_size=int(config["evaluation"]["test_batch"]),
        workers=int(config["evaluation"]["dataloader_workers"]),
    )

    test_paths = [splits.full_val_set.samples[index][0] for index in splits.test_set.indices]
    image_hashes = [data_eval.file_sha256(Path(path)) for path in test_paths]

    pairs = {"cpu": ["A", "Q"], "cuda:0": ["A", "P"]}
    summary = {"split_fingerprint": splits.fingerprint, "image_count": splits.test_count, "results": {}}
    for device_spec, names in pairs.items():
        device = device_of(device_spec)
        for name in names:
            model = load_frozen_model(config, name)
            model.to(device).eval()
            metrics = data_eval.evaluate(
                model, loader, device, collect_predictions=True, relax_determinism=(name == "Q")
            )
            cm = data_eval.confusion_matrix(metrics["labels"], metrics["preds"])
            macro = data_eval.macro_metrics(cm)
            key = f"{device_spec}:{name}"
            result = {
                "device": device_spec,
                "model": name,
                "samples": int(metrics["samples"]),
                "top1": float(metrics["top1"]),
                "top5": float(metrics["top5"]),
                "ce": float(metrics["ce"]),
                "macro_precision": macro["macro_precision"],
                "macro_recall": macro["macro_recall"],
                "macro_f1": macro["macro_f1"],
                "model_sha256": data_eval.file_sha256(ensure_runs_dir() / "frozen" / f"{name}.pt"),
                "split_fingerprint": splits.fingerprint,
            }
            summary["results"][key] = result
            write_json(run_dir / f"summary_{device_spec.replace(':', '')}_{name}.json", result)
            # softmax over the frozen scores -> reported confidence of the predicted class
            probabilities = torch.softmax(torch.from_numpy(metrics["logits"]), dim=1).numpy()
            with (run_dir / f"per_image_{device_spec.replace(':', '')}_{name}.csv").open(
                "w", newline="", encoding="utf-8"
            ) as handle:
                writer = csv.writer(handle)
                writer.writerow(["relative_path", "image_sha256", "label_index", "label_name", "pred_index",
                                 "pred_name", "correct", "confidence"])
                for row in range(metrics["samples"]):
                    index = int(metrics["indices"][row])
                    label_index = int(metrics["labels"][row])
                    pred_index = int(metrics["preds"][row])
                    confidence = float(probabilities[row][pred_index])
                    writer.writerow(
                        [
                            Path(test_paths[index]).resolve().relative_to(Path(splits.data_root).resolve() / "val").as_posix(),
                            image_hashes[index],
                            label_index,
                            splits.classes[label_index],
                            pred_index,
                            splits.classes[pred_index],
                            int(label_index == pred_index),
                            f"{confidence:.6f}",
                        ]
                    )
            with (run_dir / f"per_class_{device_spec.replace(':', '')}_{name}.csv").open(
                "w", newline="", encoding="utf-8"
            ) as handle:
                writer = csv.writer(handle)
                writer.writerow(["class_index", "class_name", "support", "precision", "recall", "f1"])
                for class_index, class_name in enumerate(splits.classes):
                    writer.writerow(
                        [
                            class_index,
                            class_name,
                            int(macro["support"][class_index]),
                            f"{macro['per_class_precision'][class_index]:.6f}",
                            f"{macro['per_class_recall'][class_index]:.6f}",
                            f"{macro['per_class_f1'][class_index]:.6f}",
                        ]
                    )
            np.savez_compressed(run_dir / f"confusion_{device_spec.replace(':', '')}_{name}.npz", cm)
            print(f"{key}: top1={result['top1']:.6f} top5={result['top5']:.6f} f1={result['macro_f1']:.6f}")
            del metrics
    write_json(run_dir / "summary.json", summary)
    return 0


def cmd_benchmark(args) -> int:
    """Single model/device/batch measurement in its own process (step 9)."""
    require("timing_benchmark")
    import statistics
    import time as time_module

    import data_eval
    import model_ops
    import numpy as np

    config = load_config()
    pairs = config["timing"]["device_model_pairs"]
    if args.model not in pairs.get(args.device, []):
        raise SystemExit(f"{args.model} is not part of the fixed {args.device} comparison")
    if args.batch not in config["timing"]["batch_sizes"]:
        raise SystemExit(f"batch {args.batch} is not one of the fixed batch sizes")
    if args.device == "cpu":
        torch.set_num_threads(int(config["environment"]["cpu_threads"]))
    device = device_of(args.device)
    model = load_frozen_model(config, args.model).to(device).eval()

    splits = data_eval.Splits(config)
    labelled = data_eval.IndexedDataset(splits.val_set)
    loader = data_eval.make_eval_loader(labelled, batch_size=1)
    images = []
    for batch in loader:
        images.append(batch[0])
        if len(images) == 32:
            break
    batch_input = torch.cat(images, dim=0).to(device)
    while batch_input.size(0) < args.batch:
        batch_input = torch.cat([batch_input, batch_input], dim=0)
    batch_input = batch_input[: args.batch].contiguous()

    def synchronize() -> None:
        if device.type == "cuda":
            torch.cuda.synchronize()

    with model_ops.relaxed_determinism(args.model == "Q"), torch.no_grad():
        for _ in range(int(config["timing"]["warmup_iterations"])):
            model(batch_input)
        synchronize()
        rounds = []
        for _ in range(int(config["timing"]["rounds"])):
            timings = []
            for _ in range(int(config["timing"]["measured_iterations"])):
                synchronize()
                start = time_module.perf_counter()
                model(batch_input)
                synchronize()
                timings.append((time_module.perf_counter() - start) * 1000.0)
            timings.sort()
            rounds.append(timings)
    latencies = [statistics.median(round_values) for round_values in rounds]
    p95 = [round_values[int(math.ceil(0.95 * len(round_values))) - 1] for round_values in rounds]
    throughput = [args.batch / (median / 1000.0) for median in latencies]
    payload = {
        "model": args.model,
        "device": args.device,
        "batch_size": int(args.batch),
        "warmup_iterations": int(config["timing"]["warmup_iterations"]),
        "measured_iterations": int(config["timing"]["measured_iterations"]),
        "rounds": int(config["timing"]["rounds"]),
        "round_median_ms": latencies,
        "round_p95_ms": p95,
        "round_throughput_per_s": throughput,
        "median_ms": float(statistics.median(latencies)),
        "p95_ms": float(statistics.median(p95)),
        "throughput_mean": float(np.mean(throughput)),
        "throughput_std": float(np.std(throughput, ddof=1)) if len(throughput) > 1 else 0.0,
        "scope": "model inference only; no disk IO, preprocessing, HTTP or web time",
    }
    run_dir = ensure_runs_dir() / "timing"
    write_json(run_dir / f"{args.device.replace(':', '')}_{args.model}_bs{args.batch}.json", payload)
    print(json.dumps(payload, indent=2))
    return 0


def cmd_benchmark_all(args) -> int:
    """Run every fixed combination in its own process."""
    require("timing_benchmark")
    config = load_config()
    results = []
    for device, names in config["timing"]["device_model_pairs"].items():
        for name in names:
            for batch in config["timing"]["batch_sizes"]:
                command = [sys.executable, str(Path(__file__)), "benchmark",
                           "--model", name, "--device", device, "--batch", str(batch)]
                print("running:", " ".join(command), flush=True)
                code = subprocess.call(command, cwd=str(EXPERIMENT_DIR))
                results.append({"model": name, "device": device, "batch": batch, "exit": code})
    write_json(ensure_runs_dir() / "timing" / "index.json", {"runs": results})
    return 0 if all(item["exit"] == 0 for item in results) else 3


# --------------------------------------------------------------------------- #
# selftest / smoke
# --------------------------------------------------------------------------- #
def cmd_selftest(args) -> int:
    print("running unit tests (engineering checks only, no training, no test split)", flush=True)
    code = subprocess.call(
        [sys.executable, "-m", "unittest", "discover", "-s", str(EXPERIMENT_DIR), "-p", "test_*.py", "-v"],
        cwd=str(EXPERIMENT_DIR),
    )
    return code


def cmd_smoke(args) -> int:
    import smoke

    return smoke.main()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description=(
            "Experiment 3: INT8 static quantization and structured channel pruning of the "
            "experiment-2 ResNet-50. All parameters come from the frozen config.json; "
            "gated subcommands refuse to run when execution_permissions.json does not allow them."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "current scope: only config-check / selftest / smoke are authorized.\n"
            "long stages (audit, baseline, quantize, prune-screen, finetune, freeze, evaluate,\n"
            "benchmark) each need their explicit permission in execution_permissions.json."
        ),
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("config-check", help="verify the frozen config hash and print the fixed settings")
    sub.add_parser("selftest", help="run the engineering unit tests")
    sub.add_parser("smoke", help="run the engineering smoke checks")
    sub.add_parser("audit", help="[gated] full data fingerprint audit")
    sub.add_parser("baseline", help="[gated] measure model A on the validation split")
    sub.add_parser("quantize", help="[gated] calibration tiers and INT8 selection")
    sub.add_parser("prune-screen", help="[gated] build and screen the three pruning ratios")
    finetune = sub.add_parser("finetune", help="[gated] fine-tune the selected pruned model")
    finetune.add_argument("--resume", action="store_true", help="resume from checkpoint_last.pt")
    sub.add_parser("freeze", help="[gated] export A/Q/P TorchScript files")
    sub.add_parser("evaluate", help="[gated] final test-split evaluation")
    benchmark = sub.add_parser("benchmark", help="[gated] measure one model/device/batch combination")
    benchmark.add_argument("--model", required=True, choices=["A", "Q", "P"])
    benchmark.add_argument("--device", required=True, choices=["cpu", "cuda:0"])
    benchmark.add_argument("--batch", required=True, type=int)
    sub.add_parser("benchmark-all", help="[gated] measure every fixed combination, one process each")
    return parser


HANDLERS = {
    "config-check": cmd_config_check,
    "selftest": cmd_selftest,
    "smoke": cmd_smoke,
    "audit": cmd_audit,
    "baseline": cmd_baseline,
    "quantize": cmd_quantize,
    "prune-screen": cmd_prune_screen,
    "finetune": cmd_finetune,
    "freeze": cmd_freeze,
    "evaluate": cmd_evaluate,
    "benchmark": cmd_benchmark,
    "benchmark-all": cmd_benchmark_all,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        print("\nno subcommand given; nothing was run.")
        return 0
    handler = HANDLERS[args.command]
    return int(handler(args))


if __name__ == "__main__":
    sys.exit(main())

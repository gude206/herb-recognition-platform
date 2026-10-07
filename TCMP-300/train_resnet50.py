"""Fine-tune ResNet-50 on TCMP-300 without random training augmentation."""

import argparse
import csv
import hashlib
import json
import os
import warnings
from pathlib import Path

import torch
from PIL import ImageFile
from torch import nn
from torch.utils.data import DataLoader, RandomSampler, Subset
from torchvision import datasets, models, transforms

from experiment_repro import (
    REPRO_VERSION, EpochSeededDataset, capture_rng_state, configure_randomness,
    load_checkpoint, resume_randomness, run_config, software_versions, validate_resume_config,
)


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "author_tcmp_300" / "images" / "tcmp-300"
SPLITS = ROOT / "data" / "author_tcmp_300" / "splits"
VAL_MANIFEST = SPLITS / "val.csv"
TEST_MANIFEST = SPLITS / "test.csv"
NORMALIZE = transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
# A few author-provided JPEGs have short trailers but still decode correctly.
ImageFile.LOAD_TRUNCATED_IMAGES = True


def parse_args(default_output_dir=None, description=None):
    parser = argparse.ArgumentParser(description=description or __doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA)
    parser.add_argument("--val-manifest", type=Path, default=VAL_MANIFEST)
    parser.add_argument("--test-manifest", type=Path, default=TEST_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=default_output_dir or ROOT / "runs" / "resnet50_7030_baseline")
    parser.add_argument("--epochs", type=int, default=20, help="Total epoch limit, including completed epochs when resuming")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--accumulation", type=int, default=2)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42, help="Shared random seed for comparable fresh runs")
    parser.add_argument("--deterministic", action="store_true", help="Require deterministic Torch operations for reproducible epoch-boundary resumes on the same software and hardware")
    parser.add_argument("--proxy", help="Proxy for downloading ImageNet weights if needed")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--patience", type=int, default=3, help="Stop after this many consecutive epochs with insufficient validation improvement")
    parser.add_argument("--min-delta-percent", type=float, default=0.01, help="Minimum validation accuracy gain in percentage points")
    parser.add_argument("--resume-backbone-lr", type=float, default=3e-5)
    parser.add_argument("--resume-head-lr", type=float, default=3e-4)
    parser.add_argument("--max-train-batches", type=int, default=0, help="Smoke-test limit; 0 uses the full set")
    parser.add_argument("--max-val-batches", type=int, default=0, help="Smoke-test limit; 0 uses the full set")
    return parser.parse_args()


def make_eval_transform():
    return transforms.Compose(
        [
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            NORMALIZE,
        ]
    )


def manifest_indices(manifest_path, image_set, data_root):
    lookup = {
        Path(path).resolve().relative_to(data_root).as_posix(): (index, label)
        for index, (path, label) in enumerate(image_set.samples)
    }
    indices = []
    seen = set()
    with manifest_path.open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != ["relative_path", "class_name"]:
            raise ValueError(f"Invalid split manifest columns: {manifest_path}")
        for row in reader:
            relative_path = row["relative_path"]
            if relative_path in seen or relative_path not in lookup:
                raise ValueError(f"Duplicate or unknown image in {manifest_path}: {relative_path}")
            index, label = lookup[relative_path]
            if image_set.classes[label] != row["class_name"]:
                raise ValueError(f"Class mismatch in {manifest_path}: {relative_path}")
            seen.add(relative_path)
            indices.append(index)
    if not indices:
        raise ValueError(f"Empty split manifest: {manifest_path}")
    return indices


def split_fingerprint(val_manifest, test_manifest):
    digest = hashlib.sha256()
    for path in (val_manifest, test_manifest):
        digest.update(path.read_bytes())
        digest.update(b"\n")
    return digest.hexdigest()


def make_loaders(args, device, train_transform=None):
    data_root = args.data_dir.resolve()
    val_transform = make_eval_transform()
    if train_transform is None:
        train_transform = make_eval_transform()
    train_set = datasets.ImageFolder(data_root / "train", transform=train_transform)
    full_val_set = datasets.ImageFolder(data_root / "val", transform=val_transform)
    if train_set.classes != full_val_set.classes:
        raise ValueError("Train and validation class folders do not match")
    if len(train_set.classes) != 300:
        raise ValueError(f"Expected 300 classes, found {len(train_set.classes)}")
    val_indices = manifest_indices(args.val_manifest, full_val_set, data_root)
    test_indices = manifest_indices(args.test_manifest, full_val_set, data_root)
    if set(val_indices).intersection(test_indices) or len(val_indices) + len(test_indices) != len(full_val_set):
        raise ValueError("Validation and test manifests must be disjoint and cover the author's full validation set")
    val_set = Subset(full_val_set, val_indices)
    options = {
        "batch_size": args.batch_size,
        "num_workers": args.workers,
        "pin_memory": device.type == "cuda",
        "persistent_workers": args.workers > 0,
    }
    generators = {name: torch.Generator().manual_seed(args.seed + offset)
                  for offset, name in enumerate(("shuffle", "train_workers", "val_workers"))}
    seeded_train_set = EpochSeededDataset(train_set, args.seed)
    train_loader = DataLoader(
        seeded_train_set, sampler=RandomSampler(seeded_train_set, generator=generators["shuffle"]),
        generator=generators["train_workers"], **options,
    )
    val_loader = DataLoader(val_set, shuffle=False, generator=generators["val_workers"], **options)
    train_loader.repro_generators = generators
    return train_loader, val_loader, train_set.classes, split_fingerprint(args.val_manifest, args.test_manifest), len(test_indices)


def run_epoch(model, loader, criterion, device, scaler, optimizer=None, accumulation=1, max_batches=0):
    training = optimizer is not None
    model.train(training)
    if training:
        optimizer.zero_grad(set_to_none=True)
    total_loss = 0.0
    correct = 0
    seen = 0
    batch_count = min(len(loader), max_batches) if max_batches else len(loader)
    for step, (images, labels) in enumerate(loader, 1):
        if step > batch_count:
            break
        images = images.to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)
        with torch.set_grad_enabled(training):
            with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
                logits = model(images)
                loss = criterion(logits, labels)
            if training:
                group_size = min(accumulation, batch_count - ((step - 1) // accumulation) * accumulation)
                scaler.scale(loss / group_size).backward()
                if step % accumulation == 0 or step == batch_count:
                    scaler.step(optimizer)
                    scaler.update()
                    optimizer.zero_grad(set_to_none=True)
        size = labels.size(0)
        total_loss += loss.item() * size
        correct += (logits.argmax(dim=1) == labels).sum().item()
        seen += size
        if training and (step % 200 == 0 or step == batch_count):
            print(f"  batch {step}/{batch_count}, loss={total_loss / seen:.4f}, acc={correct / seen:.2%}", flush=True)
    return total_loss / seen, correct / seen, seen


def update_early_stopping(best_accuracy, val_accuracy, stale_epochs, min_delta):
    improvement = val_accuracy - best_accuracy
    stale_epochs = 0 if improvement + 1e-12 >= min_delta else stale_epochs + 1
    return max(best_accuracy, val_accuracy), stale_epochs, improvement


def main(train_transform=None, default_output_dir=None, augmentation="none", description=None):
    args = parse_args(default_output_dir, description)
    if args.batch_size < 1 or args.accumulation < 1 or args.epochs < 1 or args.patience < 1:
        raise ValueError("Batch size, accumulation, epochs and patience must be positive")
    if args.min_delta_percent < 0:
        raise ValueError("Minimum accuracy improvement cannot be negative")
    if args.workers < 0 or args.max_train_batches < 0 or args.max_val_batches < 0:
        raise ValueError("Workers and batch limits cannot be negative")
    if args.proxy:
        os.environ["HTTPS_PROXY"] = args.proxy
        os.environ["HTTP_PROXY"] = args.proxy
    configure_randomness(args.seed, args.deterministic)
    torch.set_num_threads(min(4, os.cpu_count() or 4))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    last_path = args.output_dir / "last.pt"
    metrics_path = args.output_dir / "metrics.csv"
    if not args.resume:
        existing = [path for path in (metrics_path, last_path, args.output_dir / "best.pt") if path.exists()]
        if existing:
            raise FileExistsError(f"Output directory already contains training results: {existing}. Use --resume or a new --output-dir.")
    torch.hub.set_dir(str(ROOT / "weights" / "torch_hub"))
    train_loader, val_loader, classes, split_hash, test_count = make_loaders(args, device, train_transform)
    configuration = run_config(args)
    versions = software_versions(device)
    generators = train_loader.repro_generators
    print(f"Device: {device}; classes: {len(classes)}; train: {len(train_loader.dataset)}; val: {len(val_loader.dataset)}; held-out test: {test_count}", flush=True)

    model = models.resnet50(weights=None if args.resume else models.ResNet50_Weights.IMAGENET1K_V2)
    model.fc = nn.Linear(model.fc.in_features, len(classes))
    model.to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(
        [
            {"params": [parameter for name, parameter in model.named_parameters() if not name.startswith("fc.")], "lr": 1e-4},
            {"params": model.fc.parameters(), "lr": 1e-3},
        ],
        weight_decay=1e-4,
    )
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")
    start_epoch = 1
    best_accuracy = -1.0
    stale_epochs = 0
    legacy_resume = False
    if args.resume:
        checkpoint = load_checkpoint(last_path)
        if checkpoint.get("split_hash") != split_hash:
            raise ValueError("Checkpoint uses a different data split. Start a fresh run in a new output directory.")
        if checkpoint.get("augmentation") != augmentation:
            raise ValueError(
                f"Checkpoint augmentation is {checkpoint.get('augmentation', 'unknown')!r}; "
                f"this script expects {augmentation!r}. Use a matching checkpoint or start a new run."
            )
        if checkpoint["classes"] != classes:
            raise ValueError("Checkpoint class order does not match this run")
        if checkpoint.get("run_config"):
            validate_resume_config(checkpoint["run_config"], configuration)
        if checkpoint.get("software_versions") and checkpoint["software_versions"] != versions:
            warnings.warn("Software or hardware differs from the checkpoint; exact numerical replay is not guaranteed.", RuntimeWarning)
        model.load_state_dict(checkpoint["model"])
        optimizer.load_state_dict(checkpoint["optimizer"])
        scaler.load_state_dict(checkpoint["scaler"])
        start_epoch = checkpoint["epoch"] + 1
        best_accuracy = checkpoint["best_accuracy"]
        if start_epoch > args.epochs:
            raise ValueError(f"Checkpoint already completed epoch {checkpoint['epoch']}; --epochs must be larger")
        if "early_stopping" in checkpoint:
            stale_epochs = checkpoint["early_stopping"]["stale_epochs"]
            scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=1)
            scheduler.load_state_dict(checkpoint["scheduler"])
        else:
            # The original five-epoch cosine schedule reached zero LR. Start a
            # smaller fresh schedule while keeping its model and optimizer state.
            optimizer.param_groups[0]["lr"] = args.resume_backbone_lr
            optimizer.param_groups[1]["lr"] = args.resume_head_lr
            scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
                optimizer, T_max=args.epochs - checkpoint["epoch"]
            )
        legacy_resume = resume_randomness(checkpoint, generators)
        print(f"Resuming at epoch {start_epoch}; best validation accuracy: {best_accuracy:.2%}; learning rates: {[group['lr'] for group in optimizer.param_groups]}", flush=True)
    else:
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)

    experiment = {"run_config": configuration, "software_versions": versions,
                  "rng_scheme": REPRO_VERSION, "augmentation": augmentation, "split_hash": split_hash,
                  "resume_granularity": "completed_epoch", "legacy_resume": legacy_resume}
    (args.output_dir / "run_metadata.json").write_text(json.dumps(experiment, indent=2) + "\n", encoding="utf-8")

    if not args.resume:
        with metrics_path.open("w", newline="", encoding="utf-8") as file:
            csv.writer(file).writerow(["epoch", "train_loss", "train_accuracy", "val_loss", "val_accuracy", "train_images", "val_images"])
    for epoch in range(start_epoch, args.epochs + 1):
        train_loader.dataset.set_epoch(epoch)
        print(f"Epoch {epoch}/{args.epochs}", flush=True)
        train_loss, train_acc, train_seen = run_epoch(
            model, train_loader, criterion, device, scaler, optimizer, args.accumulation, args.max_train_batches
        )
        val_loss, val_acc, val_seen = run_epoch(
            model, val_loader, criterion, device, scaler, max_batches=args.max_val_batches
        )
        scheduler.step()
        print(f"Epoch {epoch}: train {train_acc:.2%} / {train_loss:.4f}; val {val_acc:.2%} / {val_loss:.4f}", flush=True)
        with metrics_path.open("a", newline="", encoding="utf-8") as file:
            csv.writer(file).writerow([epoch, train_loss, train_acc, val_loss, val_acc, train_seen, val_seen])
        previous_best = best_accuracy
        best_accuracy, stale_epochs, improvement = update_early_stopping(
            best_accuracy, val_acc, stale_epochs, args.min_delta_percent / 100
        )
        if val_acc > previous_best:
            torch.save({"model": model.state_dict(), "classes": classes, "epoch": epoch,
                        "val_accuracy": val_acc, "augmentation": augmentation, "split_hash": split_hash,
                        "run_config": configuration, "software_versions": versions, "rng_scheme": REPRO_VERSION},
                       args.output_dir / "best.pt")
        torch.save(
            {
                "model": model.state_dict(),
                "optimizer": optimizer.state_dict(),
                "scheduler": scheduler.state_dict(),
                "scaler": scaler.state_dict(),
                "classes": classes,
                "epoch": epoch,
                "best_accuracy": best_accuracy,
                "augmentation": augmentation,
                "split_hash": split_hash,
                "early_stopping": {"stale_epochs": stale_epochs},
                "rng_state": capture_rng_state(generators),
                "rng_scheme": REPRO_VERSION,
                "run_config": configuration,
                "software_versions": versions,
            },
            last_path,
        )
        print(f"  accuracy gain vs. best: {improvement * 100:+.4f} percentage points; insufficient improvement: {stale_epochs}/{args.patience}", flush=True)
        if stale_epochs >= args.patience:
            print(f"Early stopping at epoch {epoch}", flush=True)
            break
    print(f"Done. Best validation accuracy: {best_accuracy:.2%}", flush=True)


if __name__ == "__main__":
    main()

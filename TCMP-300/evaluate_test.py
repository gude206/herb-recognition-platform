"""Evaluate a selected 70/30-split checkpoint on the held-out test images."""

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path

import torch
from PIL import Image
from torch import nn
from torch.utils.data import DataLoader, Dataset
from torchvision import datasets, models

from train_resnet50 import DATA, TEST_MANIFEST, VAL_MANIFEST, make_eval_transform, manifest_indices, split_fingerprint
from compare_predictions import dataset_fingerprint, file_sha256
from experiment_repro import load_checkpoint, software_versions


class PredictionDataset(Dataset):
    """Decode and fingerprint the same bytes so predictions bind to image content."""
    def __init__(self, image_set, indices, data_root):
        self.image_set, self.indices, self.data_root = image_set, indices, data_root

    def __len__(self):
        return len(self.indices)

    def __getitem__(self, index):
        path, label = self.image_set.samples[self.indices[index]]
        payload = Path(path).read_bytes()
        with Image.open(io.BytesIO(payload)) as image:
            image = image.convert("RGB")
        image = self.image_set.transform(image)
        relative_path = Path(path).resolve().relative_to(self.data_root).as_posix()
        return image, label, relative_path, hashlib.sha256(payload).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path, help="Selected best.pt from a run using the fixed 70/30 split")
    parser.add_argument("--data-dir", type=Path, default=DATA)
    parser.add_argument("--val-manifest", type=Path, default=VAL_MANIFEST)
    parser.add_argument("--test-manifest", type=Path, default=TEST_MANIFEST)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--output-dir", type=Path, help="Defaults to test_evaluation beside the checkpoint")
    args = parser.parse_args()
    if args.batch_size < 1 or args.workers < 0:
        raise ValueError("Batch size must be positive and workers cannot be negative")

    checkpoint = load_checkpoint(args.checkpoint)
    expected_hash = split_fingerprint(args.val_manifest, args.test_manifest)
    if checkpoint.get("split_hash") != expected_hash:
        raise ValueError("Checkpoint was not trained with these validation/test manifests")

    data_root = args.data_dir.resolve()
    full_set = datasets.ImageFolder(data_root / "val", transform=make_eval_transform())
    if checkpoint["classes"] != full_set.classes:
        raise ValueError("Checkpoint classes do not match the test data")
    indices = manifest_indices(args.test_manifest, full_set, data_root)
    val_indices = manifest_indices(args.val_manifest, full_set, data_root)
    if set(indices).intersection(val_indices) or len(indices) + len(val_indices) != len(full_set):
        raise ValueError("Validation and test manifests must be disjoint and cover the author's validation set")
    device = torch.device("cuda" if args.device == "auto" and torch.cuda.is_available() else
                          "cpu" if args.device == "auto" else args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA was requested but is unavailable")
    test_loader = DataLoader(
        PredictionDataset(full_set, indices, data_root),
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=args.workers,
        pin_memory=device.type == "cuda",
    )

    torch.set_num_threads(min(4, os.cpu_count() or 4))
    model = models.resnet50(weights=None)
    model.fc = nn.Linear(model.fc.in_features, len(full_set.classes))
    model.load_state_dict(checkpoint["model"])
    model.to(device).eval()

    correct = 0
    top5_correct = 0
    loss_sum = 0.0
    total = 0
    true_labels = []
    predicted_labels = []
    prediction_rows = []
    criterion = nn.CrossEntropyLoss(reduction="sum")
    with torch.inference_mode():
        for step, (images, labels, relative_paths, image_hashes) in enumerate(test_loader, 1):
            images = images.to(device, non_blocking=True)
            labels = labels.to(device, non_blocking=True)
            with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
                logits = model(images)
                loss = criterion(logits, labels)
            predictions = logits.argmax(dim=1)
            # Stable ordering keeps Top-1 identical to argmax even for tied logits.
            top_indices = logits.float().argsort(dim=1, descending=True, stable=True)[:, :5]
            scores = logits.float().softmax(dim=1).gather(1, top_indices)
            correct += (predictions == labels).sum().item()
            top5_correct += (top_indices == labels.unsqueeze(1)).any(dim=1).sum().item()
            loss_sum += loss.item()
            total += labels.size(0)
            true_labels.extend(labels.cpu().tolist())
            predicted_labels.extend(predictions.cpu().tolist())
            for path, sha256, truth, ranked_labels, ranked_scores in zip(
                    relative_paths, image_hashes, labels.cpu().tolist(),
                    top_indices.cpu().tolist(), scores.cpu().tolist()):
                prediction_rows.append({
                    "relative_path": path, "true_label": truth, "true_class": full_set.classes[truth],
                    "top1_label": ranked_labels[0], "top1_class": full_set.classes[ranked_labels[0]],
                    "top1_score": ranked_scores[0], "top5_labels": json.dumps(ranked_labels),
                    "top5_classes": json.dumps([full_set.classes[index] for index in ranked_labels]),
                    "top5_scores": json.dumps(ranked_scores), "sha256": sha256,
                })
            if step % 100 == 0 or step == len(test_loader):
                print(f"Evaluated {total}/{len(indices)} test images", flush=True)

    class_count = len(full_set.classes)
    confusion = torch.bincount(
        torch.tensor(true_labels) * class_count + torch.tensor(predicted_labels),
        minlength=class_count * class_count,
    ).reshape(class_count, class_count)
    true_positive = confusion.diag().float()
    support = confusion.sum(dim=1)
    predicted_count = confusion.sum(dim=0)
    precision = true_positive / predicted_count.clamp_min(1)
    recall = true_positive / support.clamp_min(1)
    f1 = 2 * precision * recall / (precision + recall).clamp_min(1e-12)

    summary = {
        "checkpoint": str(args.checkpoint.resolve()),
        "epoch": checkpoint["epoch"],
        "validation_accuracy": checkpoint["val_accuracy"],
        "test_images": total,
        "test_correct": correct,
        "test_accuracy": correct / total,
        "test_top5_accuracy": top5_correct / total,
        "test_loss": loss_sum / total,
        "macro_precision": precision.mean().item(),
        "macro_recall": recall.mean().item(),
        "macro_f1": f1.mean().item(),
        "split_hash": expected_hash,
        "dataset_fingerprint": dataset_fingerprint(prediction_rows),
        "checkpoint_sha256": file_sha256(args.checkpoint),
        "classes": full_set.classes,
        "software_versions": software_versions(device),
        "evaluation_settings": {"batch_size": args.batch_size, "workers": args.workers,
                                "device": str(device), "autocast_float16": device.type == "cuda",
                                "preprocessing": "Resize256_CenterCrop224_RGB_ImageNetNormalize_v1"},
    }
    output_dir = args.output_dir or args.checkpoint.parent / "test_evaluation"
    output_dir.mkdir(parents=True, exist_ok=True)
    prediction_path = output_dir / "per_image.csv"
    with prediction_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=list(prediction_rows[0]))
        writer.writeheader()
        writer.writerows(prediction_rows)
    summary["predictions_file"] = prediction_path.name
    summary["predictions_sha256"] = file_sha256(prediction_path)
    (output_dir / "test_metrics.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (output_dir / "per_class.csv").open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(["class_index", "class_name", "support", "correct", "precision", "recall", "f1"])
        for index, class_name in enumerate(full_set.classes):
            writer.writerow([
                index,
                class_name,
                support[index].item(),
                int(true_positive[index].item()),
                precision[index].item(),
                recall[index].item(),
                f1[index].item(),
            ])
    print(json.dumps({key: value for key, value in summary.items() if key != "classes"}, ensure_ascii=False, indent=2))
    print(f"Saved test metrics, per-class and per-image results to {output_dir.resolve()}")


if __name__ == "__main__":
    main()

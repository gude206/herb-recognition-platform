"""Compare two fixed checkpoints on the same fingerprinted test images.

Usage: python compare_predictions.py EVALUATION_A EVALUATION_B --output-dir OUTPUT
Each evaluation directory must contain test_metrics.json and per_image.csv from
evaluate_test.py. Differences are always B minus A; no model selection is done.
"""

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path, PurePosixPath

import numpy as np


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dataset_fingerprint(rows):
    identities = sorted((row["relative_path"], int(row["true_label"]), row["true_class"], row["sha256"])
                        for row in rows)
    return hashlib.sha256(json.dumps(identities, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def load_evaluation(directory):
    directory = Path(directory)
    metadata = json.loads((directory / "test_metrics.json").read_text(encoding="utf-8"))
    prediction_name = metadata.get("predictions_file")
    if prediction_name != "per_image.csv":
        raise ValueError("Missing fingerprinted per_image.csv; re-evaluate this fixed checkpoint with evaluate_test.py")
    path = directory / prediction_name
    if file_sha256(path) != metadata.get("predictions_sha256"):
        raise ValueError("Prediction file checksum does not match evaluation metadata")
    classes = metadata.get("classes")
    if not classes or len(classes) != len(set(classes)):
        raise ValueError("Evaluation class mapping is missing or ambiguous")
    with path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    required = {"relative_path", "true_label", "true_class", "top1_label", "top1_class", "top1_score",
                "top5_labels", "top5_classes", "top5_scores", "sha256"}
    seen = set()
    for row in rows:
        if set(row) != required:
            raise ValueError("Invalid prediction columns")
        relative_path = PurePosixPath(row["relative_path"])
        if not row["relative_path"] or relative_path.is_absolute() or ".." in relative_path.parts or "\\" in row["relative_path"]:
            raise ValueError("Prediction image path must be a canonical relative path")
        if relative_path.as_posix() != row["relative_path"] or row["relative_path"] in seen:
            raise ValueError("Duplicate or noncanonical prediction image path")
        seen.add(row["relative_path"])
        if re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is None:
            raise ValueError("Missing or invalid image SHA-256")
        row["true_label"], row["top1_label"] = int(row["true_label"]), int(row["top1_label"])
        ranked_labels = json.loads(row["top5_labels"])
        ranked_classes, scores = json.loads(row["top5_classes"]), json.loads(row["top5_scores"])
        if len(ranked_labels) != min(5, len(classes)) or len(set(ranked_labels)) != len(ranked_labels):
            raise ValueError("Invalid Top-5 labels")
        labels = [row["true_label"], row["top1_label"], *ranked_labels]
        if any(type(label) is not int or not 0 <= label < len(classes) for label in labels):
            raise ValueError("Prediction labels do not belong to the class mapping")
        if row["true_class"] != classes[row["true_label"]] or row["top1_class"] != classes[row["top1_label"]]:
            raise ValueError("Prediction label/name mapping is inconsistent")
        if ranked_classes != [classes[index] for index in ranked_labels] or ranked_labels[0] != row["top1_label"]:
            raise ValueError("Top-1 and Top-5 class mapping is inconsistent")
        if len(scores) != len(ranked_labels) or any(not isinstance(score, (float, int)) or
                not math.isfinite(score) or not 0 <= score <= 1 for score in scores):
            raise ValueError("Invalid prediction scores")
        if scores != sorted(scores, reverse=True) or not math.isclose(float(row["top1_score"]), scores[0], abs_tol=1e-8):
            raise ValueError("Top-1 and Top-5 scores are inconsistent")
        row["top1_correct"] = row["top1_label"] == row["true_label"]
        row["top5_correct"] = row["true_label"] in ranked_labels
    if not rows or len(rows) != metadata.get("test_images"):
        raise ValueError("Prediction count does not match evaluation metadata")
    if dataset_fingerprint(rows) != metadata.get("dataset_fingerprint"):
        raise ValueError("Image/ground-truth fingerprint does not match evaluation metadata")
    if sum(row["top1_correct"] for row in rows) != metadata.get("test_correct"):
        raise ValueError("Per-image Top-1 results disagree with evaluation summary")
    for metric in ("top1", "top5"):
        key = "test_accuracy" if metric == "top1" else "test_top5_accuracy"
        if not math.isclose(sum(row[metric + "_correct"] for row in rows) / len(rows), metadata[key], abs_tol=1e-10):
            raise ValueError("Per-image accuracy disagrees with evaluation summary")
    return metadata, {row["relative_path"]: row for row in rows}


def exact_mcnemar(only_a, only_b):
    discordant = int(only_a + only_b)
    if not discordant:
        return 1.0
    tail = min(int(only_a), int(only_b))
    logs = [math.lgamma(discordant + 1) - math.lgamma(index + 1) -
            math.lgamma(discordant - index + 1) - discordant * math.log(2)
            for index in range(tail + 1)]
    peak = max(logs)
    return min(1.0, 2 * math.exp(peak) * sum(math.exp(value - peak) for value in logs))


def paired_statistics(correct_a, correct_b, bootstrap_samples, seed):
    if bootstrap_samples < 100 or len(correct_a) == 0 or len(correct_a) != len(correct_b):
        raise ValueError("Pair counts must match and bootstrap samples must be at least 100")
    a, b = np.asarray(correct_a, dtype=bool), np.asarray(correct_b, dtype=bool)
    only_a, only_b = int(np.sum(a & ~b)), int(np.sum(~a & b))
    count = len(a)
    # Resampling the {-1,0,+1} paired differences via multinomial counts is the
    # same paired IID bootstrap as resampling image rows, without huge arrays.
    bootstrap = np.random.default_rng(seed).multinomial(
        count, np.asarray([only_a, count - only_a - only_b, only_b]) / count,
        size=bootstrap_samples,
    )
    lower, upper = np.quantile((bootstrap[:, 2] - bootstrap[:, 0]) / count, [0.025, 0.975])
    return {"images": count, "accuracy_a": float(a.mean()), "accuracy_b": float(b.mean()),
            "difference_b_minus_a": (only_b - only_a) / count,
            "difference_ci95": [float(lower), float(upper)], "only_a_correct": only_a,
            "only_b_correct": only_b, "both_correct": int(np.sum(a & b)),
            "both_wrong": int(np.sum(~a & ~b)), "mcnemar_exact_two_sided_p": exact_mcnemar(only_a, only_b)}


def compare_evaluations(directory_a, directory_b, bootstrap_samples=10000, seed=20261001):
    metadata_a, rows_a = load_evaluation(directory_a)
    metadata_b, rows_b = load_evaluation(directory_b)
    for key in ("split_hash", "dataset_fingerprint", "classes"):
        if not metadata_a.get(key) or metadata_a[key] != metadata_b.get(key):
            raise ValueError("Evaluations use different " + key)
    settings_a, settings_b = metadata_a.get("evaluation_settings"), metadata_b.get("evaluation_settings")
    if not settings_a or not settings_b:
        raise ValueError("Evaluation settings are missing")
    for key in ("preprocessing", "autocast_float16", "device", "batch_size"):
        if key not in settings_a or key not in settings_b or settings_a[key] != settings_b[key]:
            raise ValueError("Evaluations use different inference setting: " + key)
    if set(rows_a) != set(rows_b):
        raise ValueError("Evaluations do not cover the same image paths")
    paths = sorted(rows_a)
    for path in paths:
        for key in ("true_label", "true_class", "sha256"):
            if rows_a[path][key] != rows_b[path][key]:
                raise ValueError("Paired image has different ground truth/content: " + path)
    result = {"evaluation_a": str(Path(directory_a).resolve()), "evaluation_b": str(Path(directory_b).resolve()),
              "checkpoint_sha256_a": metadata_a.get("checkpoint_sha256"),
              "checkpoint_sha256_b": metadata_b.get("checkpoint_sha256"),
              "split_hash": metadata_a["split_hash"], "dataset_fingerprint": metadata_a["dataset_fingerprint"],
              "evaluation_settings": settings_a,
              "bootstrap_samples": bootstrap_samples, "bootstrap_seed": seed,
              "method": "paired IID image bootstrap percentile 95% CI; exact two-sided McNemar",
              "scope": "two fixed checkpoints; not an estimate of variation across training seeds"}
    for offset, metric in enumerate(("top1", "top5")):
        result[metric] = paired_statistics([rows_a[path][metric + "_correct"] for path in paths],
                                          [rows_b[path][metric + "_correct"] for path in paths],
                                          bootstrap_samples, seed + offset)
    return result


def markdown_report(result):
    lines = ["# Fixed-checkpoint paired test comparison", "", "All differences are evaluation B minus evaluation A.", "",
             "| Metric | A | B | Difference (pp) | Paired bootstrap 95% CI (pp) | Exact McNemar p |",
             "|---|---:|---:|---:|---:|---:|"]
    for metric in ("top1", "top5"):
        value = result[metric]
        lower, upper = value["difference_ci95"]
        lines.append(f"| {metric} | {value['accuracy_a']:.2%} | {value['accuracy_b']:.2%} | "
                     f"{value['difference_b_minus_a'] * 100:+.3f} | [{lower * 100:+.3f}, {upper * 100:+.3f}] | "
                     f"{value['mcnemar_exact_two_sided_p']:.4g} |")
    top1 = result["top1"]
    lower, upper = top1["difference_ci95"]
    lines += ["", f"Top-1 discordant pairs: only A correct = {top1['only_a_correct']}; only B correct = {top1['only_b_correct']}.", "",
              "The Top-1 interval includes zero; this comparison does not establish a Top-1 difference." if lower <= 0 <= upper else
              "The Top-1 interval excludes zero for these fixed checkpoints under the image bootstrap assumptions.", "",
              "Images are resampled as independent units. Correlated source images require a source-group analysis. "
              "This comparison does not measure variability across training seeds and must not be used to retune on the test set.", "",
              f"Evaluation A: {result['evaluation_a']}", f"Evaluation B: {result['evaluation_b']}",
              f"Test images: {top1['images']}; bootstrap replicates: {result['bootstrap_samples']}; seed: {result['bootstrap_seed']}.",
              f"Inference settings: {json.dumps(result['evaluation_settings'], ensure_ascii=False, sort_keys=True)}",
              f"Dataset fingerprint: {result['dataset_fingerprint']}", f"Split hash: {result['split_hash']}", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evaluation_a", type=Path)
    parser.add_argument("evaluation_b", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bootstrap-samples", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20261001)
    args = parser.parse_args()
    result = compare_evaluations(args.evaluation_a, args.evaluation_b, args.bootstrap_samples, args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "paired_comparison.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    report = markdown_report(result)
    (args.output_dir / "paired_comparison.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()

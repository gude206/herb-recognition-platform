"""Data, validation/test evaluation and statistics for experiment 3.

Everything here is a pure function of the frozen ``config.json``: no value is
read from the command line, and no split/label/augmentation is decided at run
time.

Fixed by the approved plan (see config.json):
  * train 36324 / val 11030 / test 4735 images, 300 classes, ImageFolder order;
  * eval transform = Resize(256) -> CenterCrop(224) -> ToTensor -> ImageNet norm;
  * train transform = RandomResizedCrop(224, scale=(0.8, 1.0), ratio=(0.9, 1.1))
    -> RandomHorizontalFlip(0.5) -> ToTensor -> ImageNet norm;
  * augmentation randomness for a sample is a function of (seed, epoch, index);
  * shuffle generator and worker-startup generator are separate objects.
"""

from __future__ import annotations

import contextlib
import csv
import hashlib
import json
import random
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from PIL import ImageFile
from torch.utils.data import DataLoader, Dataset, RandomSampler, Subset
from torchvision import datasets, transforms

# A few author-provided JPEGs have short trailers but still decode correctly.
ImageFile.LOAD_TRUNCATED_IMAGES = True

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)
NUM_CLASSES = 300
SEED = 42


# --------------------------------------------------------------------------- #
# preprocessing
# --------------------------------------------------------------------------- #
def eval_transform() -> transforms.Compose:
    """Calibration / validation / test: short side 256, center crop 224."""
    return transforms.Compose(
        [
            transforms.Resize(256, interpolation=transforms.InterpolationMode.BILINEAR, antialias=True),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
        ]
    )


def train_transform() -> transforms.Compose:
    """Pruning fine-tune only: RRC(224) + horizontal flip, nothing else."""
    return transforms.Compose(
        [
            transforms.RandomResizedCrop(
                224,
                scale=(0.8, 1.0),
                ratio=(0.9, 1.1),
                interpolation=transforms.InterpolationMode.BILINEAR,
                antialias=True,
            ),
            transforms.RandomHorizontalFlip(p=0.5),
            transforms.ToTensor(),
            transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
        ]
    )


# --------------------------------------------------------------------------- #
# splits
# --------------------------------------------------------------------------- #
def split_fingerprint(val_manifest: Path, test_manifest: Path) -> str:
    """sha256(val.csv bytes + b'\\n' + test.csv bytes + b'\\n').

    Identical rule to experiment 2 (train_resnet50.py:split_fingerprint), so the
    digest can be compared against the run that produced model A.
    """
    digest = hashlib.sha256()
    for path in (Path(val_manifest), Path(test_manifest)):
        digest.update(path.read_bytes())
        digest.update(b"\n")
    return digest.hexdigest()


def manifest_indices(manifest_path: Path, image_set: datasets.ImageFolder, data_root: Path) -> list[int]:
    """Map a split manifest onto indices of the author's validation ImageFolder."""
    data_root = Path(data_root).resolve()
    lookup = {
        Path(path).resolve().relative_to(data_root).as_posix(): (index, label)
        for index, (path, label) in enumerate(image_set.samples)
    }
    indices: list[int] = []
    seen: set[str] = set()
    with Path(manifest_path).open(encoding="utf-8", newline="") as file:
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


class Splits:
    """Loaded splits plus the invariants the plan requires to hold."""

    def __init__(self, config: dict):
        paths = config["paths"]
        data = config["data"]
        self.data_root = Path(paths["data_root"])
        self.val_manifest = Path(paths["val_manifest"])
        self.test_manifest = Path(paths["test_manifest"])

        self.train_set = datasets.ImageFolder(self.data_root / "train", transform=train_transform())
        self.full_val_set = datasets.ImageFolder(self.data_root / "val", transform=eval_transform())

        if self.train_set.classes != self.full_val_set.classes:
            raise ValueError("Train and validation class folders do not match")
        if len(self.train_set.classes) != data["classes"]:
            raise ValueError(f"Expected {data['classes']} classes, found {len(self.train_set.classes)}")

        val_indices = manifest_indices(self.val_manifest, self.full_val_set, self.data_root)
        test_indices = manifest_indices(self.test_manifest, self.full_val_set, self.data_root)
        if set(val_indices).intersection(test_indices):
            raise ValueError("Validation and test manifests overlap")
        if len(val_indices) + len(test_indices) != len(self.full_val_set):
            raise ValueError("Validation and test manifests do not cover the author validation set")

        self.train_count = len(self.train_set)
        self.val_count = len(val_indices)
        self.test_count = len(test_indices)
        expected = (data["train_images"], data["val_images"], data["test_images"])
        actual = (self.train_count, self.val_count, self.test_count)
        if actual != expected:
            raise ValueError(f"Split sizes {actual} differ from the frozen config {expected}")

        self.val_set = Subset(self.full_val_set, val_indices)
        self.test_set = Subset(self.full_val_set, test_indices)
        self.classes = list(self.train_set.classes)
        self.fingerprint = split_fingerprint(self.val_manifest, self.test_manifest)
        expected_fp = config["data"].get("split_fingerprint_expected")
        if expected_fp and self.fingerprint != expected_fp:
            raise ValueError(
                f"Split fingerprint {self.fingerprint} does not match the frozen {expected_fp}"
            )


def class_fingerprint(classes: list[str]) -> str:
    return hashlib.sha256(("\n".join(classes) + "\n").encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# calibration sampling
# --------------------------------------------------------------------------- #
def per_class_indices(train_set: datasets.ImageFolder) -> list[list[int]]:
    """Indices of train_set.samples grouped by class, ascending index order."""
    grouped: list[list[int]] = [[] for _ in range(len(train_set.classes))]
    for index, (_, label) in enumerate(train_set.samples):
        grouped[label].append(index)
    return grouped


def calibration_indices(
    train_set: datasets.ImageFolder, per_class: int, seed: int = SEED
) -> tuple[list[int], list[dict]]:
    """Nested per-class calibration sample: one fixed permutation per class.

    The permutation is drawn once with seed 42 over the classes in class order,
    so tier 2 is a prefix of tier 5 which is a prefix of tier 10.  Raises if a
    class has fewer images than requested - the plan forbids topping up from the
    validation or test splits.
    """
    grouped = per_class_indices(train_set)
    rng = random.Random(seed)
    chosen: list[int] = []
    rows: list[dict] = []
    for class_index, members in enumerate(grouped):
        permutation = list(range(len(members)))
        rng.shuffle(permutation)
        if len(members) < per_class:
            raise ValueError(
                f"Class {class_index} has only {len(members)} training images; "
                f"{per_class} per class requested - stopping as required"
            )
        for position in permutation[:per_class]:
            chosen.append(members[position])
        rows.append(
            {
                "class_index": class_index,
                "class_name": train_set.classes[class_index],
                "available": len(members),
                "selected": per_class,
            }
        )
    return chosen, rows


def calibration_manifest(
    train_set: datasets.ImageFolder, indices: list[int], path: Path
) -> dict:
    """Write the actual image list used for calibration and return its summary."""
    root = Path(train_set.root).resolve()
    rows = []
    for index in indices:
        sample_path, label = train_set.samples[index]
        rows.append(
            {
                "relative_path": Path(sample_path).resolve().relative_to(root).as_posix(),
                "class_index": int(label),
                "class_name": train_set.classes[label],
            }
        )
    payload = {
        "count": len(rows),
        "source": "train split only",
        "rows": rows,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


# --------------------------------------------------------------------------- #
# deterministic per-sample augmentation
# --------------------------------------------------------------------------- #
@contextlib.contextmanager
def _seeded_sample(seed: int):
    """Seed python ``random`` and the torch CPU RNG for exactly one sample."""
    py_state = random.getstate()
    torch_state = torch.get_rng_state()
    try:
        random.seed(seed)
        torch.manual_seed(seed)
        yield
    finally:
        random.setstate(py_state)
        torch.set_rng_state(torch_state)


class EpochSeededDataset(Dataset):
    """Wrap a dataset so augmentation depends only on (seed, epoch, index).

    ``epoch`` lives in shared memory so DataLoader workers started with
    ``spawn`` + ``persistent_workers=True`` observe the value set by the main
    process before each epoch instead of the value captured at worker startup.
    """

    def __init__(self, base: Dataset, seed: int = SEED, ctx=None):
        import multiprocessing as mp

        self.base = base
        self.seed = seed
        self._ctx = ctx or mp.get_context("spawn")
        self._epoch = self._ctx.Value("i", 0, lock=False)

    def __len__(self) -> int:
        return len(self.base)

    def set_epoch(self, epoch: int) -> None:
        self._epoch.value = int(epoch)

    def get_epoch(self) -> int:
        return int(self._epoch.value)

    def sample_seed(self, index: int) -> int:
        epoch = int(self._epoch.value)
        return (self.seed * 1_000_003 + epoch * 1_000_033 + index) % (2**63 - 1)

    def __getitem__(self, index: int):
        with _seeded_sample(self.sample_seed(index)):
            return self.base[index]


# --------------------------------------------------------------------------- #
# loaders
# --------------------------------------------------------------------------- #
def make_train_loader(
    train_set: datasets.ImageFolder,
    physical_batch: int,
    workers: int,
    seed: int = SEED,
    epoch: int = 0,
) -> tuple[DataLoader, EpochSeededDataset]:
    """Training loader: separate shuffle generator and worker-startup generator."""
    dataset = EpochSeededDataset(train_set, seed=seed)
    dataset.set_epoch(epoch)
    shuffle_generator = torch.Generator()
    shuffle_generator.manual_seed(seed)
    worker_generator = torch.Generator()
    worker_generator.manual_seed(seed + 1)
    loader = DataLoader(
        dataset,
        batch_size=physical_batch,
        sampler=RandomSampler(dataset, generator=shuffle_generator),
        num_workers=workers,
        pin_memory=True,
        drop_last=False,
        persistent_workers=workers > 0,
        prefetch_factor=2 if workers > 0 else None,
        multiprocessing_context="spawn" if workers > 0 else None,
        generator=worker_generator,
    )
    return loader, dataset


def make_eval_loader(dataset: Dataset, batch_size: int, workers: int = 0) -> DataLoader:
    """Validation / test loader: no shuffle, no augmentation."""
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=workers,
        pin_memory=False,
        drop_last=False,
    )


class IndexedDataset(Dataset):
    """Return (image, label, index) so predictions can be joined back to files."""

    def __init__(self, base: Dataset):
        self.base = base

    def __len__(self) -> int:
        return len(self.base)

    def __getitem__(self, index: int):
        image, label = self.base[index]
        return image, label, index


# --------------------------------------------------------------------------- #
# evaluation
# --------------------------------------------------------------------------- #
@torch.no_grad()
def evaluate(
    model: nn.Module,
    loader: DataLoader,
    device: torch.device,
    topk: tuple[int, ...] = (1, 5),
    collect_predictions: bool = False,
    relax_determinism: bool = False,
) -> dict:
    """Full-split evaluation: hard-label CE, Top-1, Top-5 (ties by class order).

    ``relax_determinism`` is only used for CPU INT8 models: PyTorch 2.5.1 has no
    deterministic implementation of the quantized CPU kernels, so the global
    deterministic flag is suspended for the duration of a quantized forward.
    """
    from model_ops import relaxed_determinism

    model.eval()
    criterion = nn.CrossEntropyLoss(reduction="sum")
    total_loss = 0.0
    seen = 0
    correct = {k: 0 for k in topk}
    labels_all: list[np.ndarray] = []
    preds_all: list[np.ndarray] = []
    logits_all: list[np.ndarray] = []
    indices_all: list[np.ndarray] = []

    with relaxed_determinism(relax_determinism):
        for batch in loader:
            if collect_predictions:
                images, labels, indices = batch
                indices_all.append(indices.numpy())
            else:
                images, labels = batch
            images = images.to(device, non_blocking=False)
            labels = labels.to(device, non_blocking=False)
            logits = model(images)
            if not torch.isfinite(logits).all():
                raise RuntimeError("Non-finite logits during evaluation - stopping as required")
            total_loss += float(criterion(logits, labels).item())
            max_k = max(topk)
            # stable descending sort: equal scores are broken by the fixed class order
            top = torch.argsort(logits, dim=1, descending=True, stable=True)[:, :max_k]
            for k in topk:
                correct[k] += int((top[:, :k] == labels.unsqueeze(1)).any(dim=1).sum().item())
            if collect_predictions:
                labels_all.append(labels.cpu().numpy())
                preds_all.append(logits.argmax(dim=1).cpu().numpy())
                logits_all.append(logits.float().cpu().numpy())
            seen += int(labels.size(0))

    if seen == 0:
        raise RuntimeError("Empty evaluation loader")
    result = {
        "samples": seen,
        "ce": total_loss / seen,
    }
    for k in topk:
        result[f"top{k}"] = correct[k] / seen
    if collect_predictions:
        result["labels"] = np.concatenate(labels_all)
        result["preds"] = np.concatenate(preds_all)
        result["logits"] = np.concatenate(logits_all)
        result["indices"] = np.concatenate(indices_all)
    return result


def confusion_matrix(y_true: np.ndarray, y_pred: np.ndarray, num_classes: int = NUM_CLASSES) -> np.ndarray:
    cm = np.zeros((num_classes, num_classes), dtype=np.int64)
    np.add.at(cm, (y_true.astype(np.int64), y_pred.astype(np.int64)), 1)
    return cm


def macro_metrics(cm: np.ndarray) -> dict:
    """Macro precision / recall / F1; zero-denominator entries count as 0."""
    tp = np.diag(cm).astype(np.float64)
    support = cm.sum(axis=1).astype(np.float64)
    predicted = cm.sum(axis=0).astype(np.float64)
    precision = np.divide(tp, predicted, out=np.zeros_like(tp), where=predicted > 0)
    recall = np.divide(tp, support, out=np.zeros_like(tp), where=support > 0)
    denominator = precision + recall
    f1 = np.divide(2.0 * precision * recall, denominator, out=np.zeros_like(tp), where=denominator > 0)
    return {
        "macro_precision": float(precision.mean()),
        "macro_recall": float(recall.mean()),
        "macro_f1": float(f1.mean()),
        "per_class_precision": precision,
        "per_class_recall": recall,
        "per_class_f1": f1,
        "support": support.astype(np.int64),
    }


# --------------------------------------------------------------------------- #
# params / theoretical main-operator cost
# --------------------------------------------------------------------------- #
def count_parameters(model: nn.Module) -> int:
    return int(sum(parameter.numel() for parameter in model.parameters()))


def conv_linear_macs(model: nn.Module, input_size: tuple[int, int, int] = (1, 3, 224, 224)) -> dict:
    """Theoretical main-operator MACs for Conv2d + Linear only.

    Counted from the real (possibly pruned) tensor shapes by a single dummy
    forward pass, so a structurally pruned model reports its true cost.
    BN, activations, pooling and residual additions are excluded from this
    number by definition; the report must state that scope.
    """
    records: list[dict] = []
    hooks = []

    def make_hook(name: str):
        def hook(module, inputs, output):
            if isinstance(module, nn.Conv2d):
                kernel = module.kernel_size[0] * module.kernel_size[1]
                macs = kernel * (module.in_channels // module.groups) * module.out_channels
                macs *= int(output.shape[-1]) * int(output.shape[-2])
            elif isinstance(module, nn.Linear):
                macs = module.in_features * module.out_features
            else:  # pragma: no cover - hook only registered on Conv2d/Linear
                return
            records.append(
                {
                    "module": name,
                    "type": type(module).__name__,
                    "macs": int(macs),
                    "out_channels": int(module.out_channels) if isinstance(module, nn.Conv2d) else int(module.out_features),
                    "in_channels": int(module.in_channels) if isinstance(module, nn.Conv2d) else int(module.in_features),
                }
            )

        return hook

    for name, module in model.named_modules():
        if isinstance(module, (nn.Conv2d, nn.Linear)):
            hooks.append(module.register_forward_hook(make_hook(name)))
    was_training = model.training
    model.eval()
    try:
        with torch.no_grad():
            model(torch.zeros(*input_size))
    finally:
        for handle in hooks:
            handle.remove()
        model.train(was_training)
    total = sum(record["macs"] for record in records)
    return {"total_macs": int(total), "total_flops": int(total * 2), "modules": records}


# --------------------------------------------------------------------------- #
# hashes
# --------------------------------------------------------------------------- #
def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


# --------------------------------------------------------------------------- #
# environment / determinism
# --------------------------------------------------------------------------- #
def configure_determinism(config: dict) -> dict:
    """Apply every fixed environment setting and return what was applied."""
    env = config["environment"]
    import os

    os.environ["CUBLAS_WORKSPACE_CONFIG"] = env["cublas_workspace_config"]
    seed = config["preprocessing"]["seed"]
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = bool(env["cudnn_benchmark"])
    torch.backends.cudnn.deterministic = bool(env["deterministic"])
    torch.backends.cuda.matmul.allow_tf32 = bool(env["tf32"])
    torch.backends.cudnn.allow_tf32 = bool(env["tf32"])
    torch.use_deterministic_algorithms(bool(env["deterministic"]))
    torch.set_num_threads(int(env["cpu_threads"]))
    try:
        torch.set_num_interop_threads(int(env["cpu_interop_threads"]))
    except RuntimeError:
        # Already initialised (e.g. a second call in the same process).
        pass
    return {
        "seed": seed,
        "torch_threads": torch.get_num_threads(),
        "torch_interop_threads": torch.get_num_interop_threads(),
        "cudnn_benchmark": torch.backends.cudnn.benchmark,
        "cudnn_deterministic": torch.backends.cudnn.deterministic,
        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
        "cublas_workspace_config": os.environ.get("CUBLAS_WORKSPACE_CONFIG"),
        "cuda_available": torch.cuda.is_available(),
        "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu",
    }


def software_versions(device: torch.device | None = None) -> dict:
    import platform

    import PIL
    import torchvision

    payload = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "torch": torch.__version__,
        "torchvision": torchvision.__version__,
        "numpy": np.__version__,
        "pillow": PIL.__version__,
        "cuda": torch.version.cuda,
        "cudnn": torch.backends.cudnn.version(),
    }
    if device is not None:
        payload["device"] = device.type
        if device.type == "cuda":
            payload["gpu"] = torch.cuda.get_device_name(0)
    return payload

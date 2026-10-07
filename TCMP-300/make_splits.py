"""Create a fixed, class-stratified 70/30 split of the author's validation images."""

import csv
import io
import json
import random
from collections import defaultdict
from pathlib import Path

from torchvision.datasets import ImageFolder


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "author_tcmp_300" / "images" / "tcmp-300"
SPLIT_DIR = ROOT / "data" / "author_tcmp_300" / "splits"
SEED = 20260927
TEST_RATIO = 0.30


def csv_text(rows):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(["relative_path", "class_name"])
    writer.writerows(rows)
    return buffer.getvalue()


def save_fixed_file(path, content):
    if path.exists():
        if path.read_bytes() != content.encode("utf-8"):
            raise FileExistsError(f"Existing split differs; refusing to overwrite: {path}")
        return
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="")
    temporary.replace(path)


def main():
    data_root = DATA.resolve()
    source = ImageFolder(data_root / "val")
    if len(source.classes) != 300:
        raise ValueError(f"Expected 300 classes, found {len(source.classes)}")

    by_class = defaultdict(list)
    for image_path, class_index in source.samples:
        relative_path = Path(image_path).resolve().relative_to(data_root).as_posix()
        by_class[class_index].append(relative_path)

    rng = random.Random(SEED)
    validation, test = [], []
    for class_index, class_name in enumerate(source.classes):
        paths = sorted(by_class[class_index])
        rng.shuffle(paths)
        test_count = min(len(paths) - 1, max(1, round(len(paths) * TEST_RATIO)))
        test.extend((path, class_name) for path in paths[:test_count])
        validation.extend((path, class_name) for path in paths[test_count:])

    validation.sort()
    test.sort()
    if len(validation) + len(test) != len(source):
        raise AssertionError("Split does not cover the full validation set")

    SPLIT_DIR.mkdir(parents=True, exist_ok=True)
    save_fixed_file(SPLIT_DIR / "val.csv", csv_text(validation))
    save_fixed_file(SPLIT_DIR / "test.csv", csv_text(test))
    metadata = {
        "source": "data/author_tcmp_300/images/tcmp-300/val",
        "seed": SEED,
        "test_ratio": TEST_RATIO,
        "classes": len(source.classes),
        "validation_images": len(validation),
        "test_images": len(test),
    }
    save_fixed_file(SPLIT_DIR / "split_info.json", json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    print(f"Created fixed split: validation={len(validation)}, test={len(test)}, classes={len(source.classes)}")


if __name__ == "__main__":
    main()

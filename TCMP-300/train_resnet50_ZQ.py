"""Fine-tune ResNet-50 on TCMP-300 with online image augmentation."""

from torchvision import transforms
from torchvision.transforms import InterpolationMode

from train_resnet50 import NORMALIZE, ROOT, main


def make_augmentation_transform():
    """PIL transforms seeded per (epoch, image) by the shared trainer."""
    return transforms.Compose(
        [
            transforms.RandomResizedCrop(
                224,
                scale=(0.8, 1.0),
                ratio=(0.9, 1.1),
                interpolation=InterpolationMode.BILINEAR,
            ),
            transforms.RandomHorizontalFlip(p=0.5),
            transforms.RandomVerticalFlip(p=0.5),
            transforms.RandomRotation(
                degrees=15,
                interpolation=InterpolationMode.BILINEAR,
            ),
            transforms.ColorJitter(
                brightness=0.3,
                contrast=0.3,
                saturation=0.2,
                hue=0.05,
            ),
        ]
    )


def make_train_transform():
    return transforms.Compose(
        [
            make_augmentation_transform(),
            transforms.ToTensor(),
            NORMALIZE,
        ]
    )


if __name__ == "__main__":
    main(
        train_transform=make_train_transform(),
        default_output_dir=ROOT / "runs" / "resnet50_7030_ZQ",
        augmentation="ZQ",
        description=__doc__,
    )

"""Epoch-boundary reproducibility for training, including persistent workers.

Every training sample gets a seed derived from (run seed, epoch, sample index).
Worker lifetime and prefetch order therefore do not change augmentation. Shuffle
uses its own generator, separate from worker startup and the model's RNG.
"""

import hashlib
import inspect
import os
import platform
import random
import warnings
from contextlib import contextmanager

import torch
from torch.utils.data import Dataset

try:
    import numpy as np
except ImportError:
    np = None


REPRO_VERSION = "epoch_sample_seed_v1"


def load_checkpoint(path):
    """Use restricted loading when available; old Torch only loads trusted files."""
    if "weights_only" in inspect.signature(torch.load).parameters:
        return torch.load(path, map_location="cpu", weights_only=True)
    warnings.warn("This Torch version has no weights_only loader; only load trusted local checkpoints.", RuntimeWarning)
    return torch.load(path, map_location="cpu")


def configure_randomness(seed, deterministic=False):
    if deterministic:
        os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    random.seed(seed)
    torch.manual_seed(seed)
    if np is not None:
        np.random.seed(seed % (2 ** 32))
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(deterministic)
    torch.backends.cudnn.benchmark = not deterministic and torch.cuda.is_available()
    torch.backends.cudnn.deterministic = deterministic
    if deterministic:
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False


def numpy_state():
    if np is None:
        return None
    name, keys, position, has_gauss, cached_gaussian = np.random.get_state()
    # Lists and built-in scalars stay compatible with torch.load(weights_only=True).
    return [name, keys.tolist(), int(position), int(has_gauss), float(cached_gaussian)]


def restore_numpy_state(state):
    if state is not None:
        if np is None:
            raise RuntimeError("Checkpoint contains NumPy RNG state but NumPy is unavailable")
        name, keys, position, has_gauss, cached_gaussian = state
        np.random.set_state((name, np.asarray(keys, dtype=np.uint32), position, has_gauss, cached_gaussian))


def capture_rng_state(generators):
    return {
        "python": random.getstate(),
        "torch_cpu": torch.get_rng_state(),
        "torch_cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else [],
        "numpy": numpy_state(),
        "generators": {name: generator.get_state() for name, generator in generators.items()},
    }


def restore_rng_state(state, generators):
    if set(state["generators"]) != set(generators):
        raise ValueError("Checkpoint DataLoader generators do not match this run")
    random.setstate(state["python"])
    torch.set_rng_state(state["torch_cpu"])
    restore_numpy_state(state.get("numpy"))
    cuda_states = state.get("torch_cuda", [])
    if cuda_states:
        if not torch.cuda.is_available() or len(cuda_states) != torch.cuda.device_count():
            raise ValueError("CUDA device count changed; exact RNG restoration is unavailable")
        torch.cuda.set_rng_state_all(cuda_states)
    for name, generator in generators.items():
        generator.set_state(state["generators"][name])


def resume_randomness(checkpoint, generators):
    if checkpoint.get("rng_state") and checkpoint.get("rng_scheme") == REPRO_VERSION:
        restore_rng_state(checkpoint["rng_state"], generators)
        return False
    warnings.warn("Legacy checkpoint has no compatible RNG state. Model/optimizer state is restored, "
                  "but shuffle and augmentation cannot exactly replay the original continuation. "
                  "Subsequent checkpoints use epoch-seeded augmentation.", RuntimeWarning)
    return True


@contextmanager
def sample_randomness(seed):
    """Seed CPU transforms without advancing model or worker RNG histories."""
    python_state, cpu_state = random.getstate(), torch.get_rng_state()
    array_state = numpy_state()
    try:
        random.seed(seed)
        # torch.manual_seed also touches CUDA; workers only need the CPU RNG.
        torch.random.default_generator.manual_seed(seed)
        if np is not None:
            np.random.seed(seed % (2 ** 32))
        yield
    finally:
        random.setstate(python_state)
        torch.set_rng_state(cpu_state)
        restore_numpy_state(array_state)


class EpochSeededDataset(Dataset):
    def __init__(self, dataset, seed):
        self.dataset = dataset
        self.seed = int(seed)
        # A shared CPU tensor carries epoch changes into persistent spawn workers.
        self.epoch = torch.zeros((), dtype=torch.int64).share_memory_()

    def __len__(self):
        return len(self.dataset)

    def set_epoch(self, epoch):
        self.epoch.fill_(int(epoch))

    def __getitem__(self, index):
        key = f"{REPRO_VERSION}:{self.seed}:{int(self.epoch.item())}:{index}"
        seed = int.from_bytes(hashlib.sha256(key.encode("ascii")).digest()[:8], "little") % (2 ** 63)
        with sample_randomness(seed):
            return self.dataset[index]


def run_config(args):
    # A proxy URL may contain credentials. Never serialize it or environment values.
    return {name: str(value) if hasattr(value, "as_posix") else value
            for name, value in vars(args).items() if name not in {"proxy", "resume"}}


def software_versions(device):
    import PIL
    import torchvision

    return {
        "python": platform.python_version(), "platform": platform.platform(),
        "torch": str(torch.__version__), "torchvision": str(torchvision.__version__),
        "pillow": PIL.__version__, "numpy": np.__version__ if np is not None else None,
        "cuda": torch.version.cuda, "cudnn": torch.backends.cudnn.version(),
        "device": str(device),
        "gpu": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
    }


def validate_resume_config(saved, current):
    fields = ("seed", "batch_size", "accumulation", "deterministic", "patience",
              "min_delta_percent", "max_train_batches", "max_val_batches")
    changed = [name for name in fields if saved.get(name) != current.get(name)]
    if changed:
        raise ValueError("Resume changes reproducibility parameters: " + ", ".join(changed))
    if saved.get("epochs") != current.get("epochs"):
        warnings.warn("Total epoch limit changed. The checkpoint's original cosine schedule is retained; "
                      "this is an extension, not an exact replay of a fresh run with the new limit.", RuntimeWarning)

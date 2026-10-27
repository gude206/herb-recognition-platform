"""Model construction, INT8 static quantization, structural channel pruning and export.

Fixed by the approved plan (see config.json):
  * A is the experiment-2 baseline best.pt (epoch 19) and is never re-trained;
  * quantization is post-training *static* quantization through the PyTorch FX
    flow on CPU/fbgemm, rebuilt from A for every calibration tier;
  * pruning deletes real internal Bottleneck channels (I1 for conv1/bn1,
    I2 for conv2/bn2, conv3 input) so tensor shapes actually shrink while the
    residual add keeps its shape;
  * A, Q and P are all exported with ``torch.jit.trace`` only - no freeze, no
    extra inference optimization.
"""

from __future__ import annotations

import contextlib
import copy
import math
from pathlib import Path

import torch
import torch.nn as nn
from torch.ao.quantization import QConfig
from torch.ao.quantization.observer import HistogramObserver, PerChannelMinMaxObserver
from torch.ao.quantization.quantize_fx import convert_fx, prepare_fx
from torchvision import models

NUM_CLASSES = 300
QUANTIZED_PREFIXES = ("torch.ao.nn.quantized", "torch.ao.nn.intrinsic.quantized")


@contextlib.contextmanager
def relaxed_determinism(enabled: bool = True):
    """Temporarily allow non-deterministic kernels.

    Two documented uses (both recorded in config.json):
      * CPU INT8 forward passes - PyTorch 2.5.1 implements no deterministic
        variant of the quantized CPU kernels;
      * the pruning fine-tune training loop - approved speed-up option B, worth
        about 2.5x per epoch.

    Everything else (validation, final evaluation, quantization baselines) runs
    with the plan's strict determinism restored.
    """
    if not enabled:
        yield
        return
    previous_algorithms = torch.are_deterministic_algorithms_enabled()
    previous_cudnn_deterministic = torch.backends.cudnn.deterministic
    torch.use_deterministic_algorithms(False)
    torch.backends.cudnn.deterministic = False
    try:
        yield
    finally:
        if previous_algorithms:
            torch.use_deterministic_algorithms(True)
        torch.backends.cudnn.deterministic = previous_cudnn_deterministic


# --------------------------------------------------------------------------- #
# model A
# --------------------------------------------------------------------------- #
def load_fp32_model(config: dict, device: str | torch.device = "cpu") -> tuple[nn.Module, dict]:
    """Rebuild A from the frozen checkpoint after checking every frozen fact."""
    from data_eval import file_sha256

    path = Path(config["paths"]["model_a_best"])
    if not path.is_file():
        raise FileNotFoundError(f"Model A not found: {path}")
    actual = file_sha256(path)
    expected = config["paths"]["model_a_sha256"]
    if actual != expected:
        raise ValueError(f"Model A sha256 {actual} does not match the approved {expected} - stopping")
    try:
        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    except Exception:  # torch < 2.6 checkpoint payload fallback
        checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    for key in ("model", "classes", "epoch", "split_hash"):
        if key not in checkpoint:
            raise ValueError(f"Checkpoint is missing '{key}' - stopping")
    classes = list(checkpoint["classes"])
    if len(classes) != NUM_CLASSES:
        raise ValueError(f"Checkpoint has {len(classes)} classes, expected {NUM_CLASSES} - stopping")
    split_hash = checkpoint.get("split_hash")
    expected_split = config["data"]["split_fingerprint_expected"]
    if split_hash and split_hash != expected_split:
        raise ValueError(f"Checkpoint split_hash {split_hash} != {expected_split} - stopping")
    if int(checkpoint["epoch"]) != int(config["paths"]["model_a_epoch"]):
        raise ValueError(
            f"Checkpoint epoch {checkpoint['epoch']} != approved {config['paths']['model_a_epoch']} - stopping"
        )
    model = models.resnet50(weights=None)
    model.fc = nn.Linear(model.fc.in_features, len(classes))
    model.load_state_dict(checkpoint["model"], strict=True)
    model.to(device)
    model.eval()
    meta = {
        "path": str(path),
        "sha256": actual,
        "epoch": int(checkpoint["epoch"]),
        "classes": classes,
        "split_hash": split_hash,
        "val_accuracy": float(checkpoint.get("val_accuracy", float("nan"))),
        "augmentation": checkpoint.get("augmentation"),
    }
    return model, meta


# --------------------------------------------------------------------------- #
# quantization (FX, static, CPU/fbgemm)
# --------------------------------------------------------------------------- #
_TORCH_DTYPE = {"quint8": torch.quint8, "qint8": torch.qint8}
_TORCH_QSCHEME = {
    "per_tensor_affine": torch.per_tensor_affine,
    "per_tensor_symmetric": torch.per_tensor_symmetric,
    "per_channel_symmetric": torch.per_channel_symmetric,
    "per_channel_affine": torch.per_channel_affine,
}


def make_qconfig(quant: dict | None = None) -> QConfig:
    """Build the qconfig from the frozen config (no hard-coded quant values).

    Revision 2 of the config changes only the activation upper bound to 255;
    every other value still comes from config.json, so the quantizer can never
    silently disagree with the recorded settings again.
    """
    quant = quant or {}
    activation = HistogramObserver.with_args(
        dtype=_TORCH_DTYPE[quant.get("activation_dtype", "quint8")],
        qscheme=_TORCH_QSCHEME[quant.get("activation_qscheme", "per_tensor_affine")],
        quant_min=int(quant.get("activation_quant_min", 0)),
        quant_max=int(quant.get("activation_quant_max", 127)),
        reduce_range=bool(quant.get("activation_reduce_range", False)),
        bins=int(quant.get("activation_observer_bins", 2048)),
    )
    weight = PerChannelMinMaxObserver.with_args(
        dtype=_TORCH_DTYPE[quant.get("weight_dtype", "qint8")],
        qscheme=_TORCH_QSCHEME[quant.get("weight_qscheme", "per_channel_symmetric")],
        ch_axis=int(quant.get("weight_ch_axis", 0)),
        quant_min=int(quant.get("weight_quant_min", -128)),
        quant_max=int(quant.get("weight_quant_max", 127)),
        reduce_range=bool(quant.get("weight_reduce_range", False)),
    )
    return QConfig(activation=activation, weight=weight)


def quantize_static_fx(
    fp32_model: nn.Module,
    config: dict,
    calibration_batches: list[torch.Tensor],
    example_input: torch.Tensor | None = None,
) -> nn.Module:
    """Post-training static quantization of A on CPU/fbgemm, no QAT, no fine-tune.

    The source model is deep-copied so every tier starts from an unmodified A.
    """
    engine = config["quantization"]["engine"]
    torch.backends.quantized.engine = engine
    qconfig_mapping = torch.ao.quantization.QConfigMapping().set_global(
        make_qconfig(config["quantization"])
    )
    example = example_input if example_input is not None else torch.randn(1, 3, 224, 224)
    model = copy.deepcopy(fp32_model).to("cpu")
    model.eval()
    prepared = prepare_fx(model, qconfig_mapping, example)
    with torch.no_grad():
        for batch in calibration_batches:
            prepared(batch.to("cpu"))
    quantized = convert_fx(prepared)
    quantized.eval()
    return quantized


def _quantized_module_type(module: nn.Module) -> str | None:
    name = type(module).__module__ or ""
    for prefix in QUANTIZED_PREFIXES:
        if name.startswith(prefix):
            return f"{name}.{type(module).__name__}"
    return None


CONTAINER_TYPE_NAMES = {"Module", "GraphModule", "Sequential", "ModuleList"}


def inspect_quantization(model: nn.Module) -> dict:
    """Check that conv/fc really became quantized operators.

    Returns counts, the ordered module list, the remaining FP32 operators and
    the quantize / dequantize boundaries found in the FX graph.
    """
    converted: list[dict] = []
    remaining_float: list[dict] = []
    float_convs = 0
    float_linears = 0
    quantized_convs = 0
    quantized_linears = 0

    for name, module in model.named_modules():
        type_name = type(module).__name__
        if type_name in CONTAINER_TYPE_NAMES:
            continue  # containers only; not compute operators
        quantized_type = _quantized_module_type(module)
        if quantized_type is not None:
            converted.append({"module": name, "type": quantized_type})
            lowered = type_name.lower()
            if "conv" in lowered:
                quantized_convs += 1
            elif lowered.endswith("linear") or lowered.endswith("linearrelu"):
                quantized_linears += 1
        elif isinstance(module, nn.Conv2d):
            float_convs += 1
            remaining_float.append({"module": name, "type": "nn.Conv2d"})
        elif isinstance(module, nn.Linear):
            float_linears += 1
            remaining_float.append({"module": name, "type": "nn.Linear"})
        elif isinstance(
            module,
            (nn.BatchNorm2d, nn.ReLU, nn.MaxPool2d, nn.AdaptiveAvgPool2d, nn.Dropout, nn.Identity, nn.Flatten),
        ):
            continue
        else:
            remaining_float.append({"module": name, "type": type_name})

    quantize_nodes: list[str] = []
    dequantize_nodes: list[str] = []
    graph = getattr(model, "graph", None)
    if graph is not None:
        for node in graph.nodes:
            target = str(node.target)
            if "quantize_per_tensor" in target or "quantize_per_channel" in target:
                quantize_nodes.append(f"{node.name} -> {target}")
            if "dequantize" in target:
                dequantize_nodes.append(f"{node.name} -> {target}")

    key_convs_quantized = quantized_convs >= len(_expected_conv_names())
    return {
        "engine": torch.backends.quantized.engine,
        "quantized_conv_count": quantized_convs,
        "quantized_linear_count": quantized_linears,
        "float_conv_count": float_convs,
        "float_linear_count": float_linears,
        "converted_module_count": len(converted),
        "converted_modules": converted,
        "remaining_float_modules": remaining_float,
        "quantize_boundaries": quantize_nodes,
        "dequantize_boundaries": dequantize_nodes,
        "key_convolutions_all_quantized": bool(key_convs_quantized),
        "claim_note": (
            "Quantization changes storage and compute type; logical parameter count stays that of A "
            "and must not be reported as a 75% structural reduction."
        ),
    }


def _expected_conv_names() -> list[str]:
    """Conv2d module names of a stock torchvision ResNet-50 (53 convolutions)."""
    return [name for name, module in models.resnet50(weights=None).named_modules() if isinstance(module, nn.Conv2d)]


# --------------------------------------------------------------------------- #
# structured channel pruning
# --------------------------------------------------------------------------- #
def l1_keep_indices(weight: torch.Tensor, keep_count: int) -> list[int]:
    """Keep the ``keep_count`` output channels with the largest L1 filter norm.

    Ties are broken by the lower original channel index; the returned list is
    sorted ascending so slicing keeps the original channel order.
    """
    if keep_count <= 0 or keep_count > weight.size(0):
        raise ValueError(f"keep_count {keep_count} out of range for {weight.size(0)} channels")
    flat = weight.detach().reshape(weight.size(0), -1)
    norms = flat.abs().sum(dim=1)
    order = sorted(range(norms.numel()), key=lambda index: (-float(norms[index]), index))
    return sorted(order[:keep_count])


def keep_count_for(original: int, ratio: float) -> int:
    """ceil((1 - ratio) * original), the plan's fixed formula."""
    if not 0.0 <= ratio < 1.0:
        raise ValueError(f"pruning ratio {ratio} outside [0, 1)")
    return int(math.ceil((1.0 - ratio) * original))


def _sliced_conv(source: nn.Conv2d, in_keep: list[int] | None, out_keep: list[int] | None) -> nn.Conv2d:
    in_channels = source.in_channels if in_keep is None else len(in_keep)
    out_channels = source.out_channels if out_keep is None else len(out_keep)
    conv = nn.Conv2d(
        in_channels,
        out_channels,
        kernel_size=source.kernel_size,
        stride=source.stride,
        padding=source.padding,
        dilation=source.dilation,
        groups=source.groups,
        bias=source.bias is not None,
        padding_mode=source.padding_mode,
    )
    weight = source.weight.detach()
    if out_keep is not None:
        weight = weight[out_keep]
    if in_keep is not None:
        weight = weight[:, in_keep]
    with torch.no_grad():
        conv.weight.copy_(weight.contiguous())
        if source.bias is not None:
            bias = source.bias.detach()
            if out_keep is not None:
                bias = bias[out_keep]
            conv.bias.copy_(bias.contiguous())
    return conv


def _sliced_bn(source: nn.BatchNorm2d, keep: list[int]) -> nn.BatchNorm2d:
    bn = nn.BatchNorm2d(
        len(keep),
        eps=source.eps,
        momentum=source.momentum,
        affine=source.affine,
        track_running_stats=source.track_running_stats,
    )
    index = torch.tensor(keep, dtype=torch.long)
    with torch.no_grad():
        if source.weight is not None:
            bn.weight.copy_(source.weight.detach()[index])
        if source.bias is not None:
            bn.bias.copy_(source.bias.detach()[index])
        if source.running_mean is not None:
            bn.running_mean.copy_(source.running_mean.detach()[index])
        if source.running_var is not None:
            bn.running_var.copy_(source.running_var.detach()[index])
        if source.num_batches_tracked is not None and bn.num_batches_tracked is not None:
            bn.num_batches_tracked.copy_(source.num_batches_tracked.detach())
    return bn


def prune_bottleneck(block: nn.Module, ratio: float, name: str) -> tuple[nn.Module, dict]:
    """Delete internal channels of one standard Bottleneck (groups == 1)."""
    for attribute in ("conv1", "conv2", "conv3", "bn1", "bn2", "bn3"):
        if not hasattr(block, attribute):
            raise TypeError(f"{name} is not a standard Bottleneck (missing {attribute})")
    if block.conv2.groups != 1:
        raise ValueError(f"{name} has groups={block.conv2.groups}; only groups=1 is supported")

    original_conv1_out = block.bn1.num_features
    original_conv2_out = block.bn2.num_features
    keep1_count = keep_count_for(original_conv1_out, ratio)
    keep2_count = keep_count_for(original_conv2_out, ratio)
    keep1 = l1_keep_indices(block.conv1.weight, keep1_count)
    keep2 = l1_keep_indices(block.conv2.weight, keep2_count)

    new_block = copy.deepcopy(block)
    new_block.conv1 = _sliced_conv(block.conv1, None, keep1)
    new_block.bn1 = _sliced_bn(block.bn1, keep1)
    new_block.conv2 = _sliced_conv(block.conv2, keep1, keep2)
    new_block.bn2 = _sliced_bn(block.bn2, keep2)
    new_block.conv3 = _sliced_conv(block.conv3, keep2, None)
    # freshly constructed modules default to training mode; the plan requires
    # every replaced layer to be put back into eval mode
    new_block.eval()

    record = {
        "block": name,
        "conv1_out_before": int(original_conv1_out),
        "conv1_out_after": int(len(keep1)),
        "conv2_out_before": int(original_conv2_out),
        "conv2_out_after": int(len(keep2)),
        "conv1_actual_ratio": float(1.0 - len(keep1) / original_conv1_out),
        "conv2_actual_ratio": float(1.0 - len(keep2) / original_conv2_out),
        "keep1": [int(i) for i in keep1],
        "keep2": [int(i) for i in keep2],
    }
    return new_block, record


def prune_resnet50(fp32_model: nn.Module, ratio: float) -> tuple[nn.Module, dict]:
    """Structurally prune every Bottleneck of a ResNet-50 at ``ratio``.

    Always starts from a deep copy of A, so the three ratios are independent
    and never cumulative.
    """
    model = copy.deepcopy(fp32_model)
    records: list[dict] = []
    layers = [model.layer1, model.layer2, model.layer3, model.layer4]
    for layer_index, layer in enumerate(layers, start=1):
        for block_index, block in enumerate(layer):
            name = f"layer{layer_index}.{block_index}"
            new_block, record = prune_bottleneck(block, ratio, name)
            layer[block_index] = new_block
            records.append(record)
    model.eval()
    total_before = sum(record["conv1_out_before"] for record in records) + sum(
        record["conv2_out_before"] for record in records
    )
    total_after = sum(record["conv1_out_after"] for record in records) + sum(
        record["conv2_out_after"] for record in records
    )
    report = {
        "requested_ratio": float(ratio),
        "bottleneck_count": len(records),
        "channel_keep_ratio": float(total_after / total_before) if total_before else 0.0,
        "actual_ratio_overall": float(1.0 - total_after / total_before) if total_before else 0.0,
        "blocks": records,
    }
    return model, report


def structural_check(model: nn.Module, input_shape: tuple[int, int, int, int] = (1, 3, 224, 224)) -> dict:
    """Forward a dummy batch and verify residual shapes stayed consistent."""
    model.eval()
    with torch.no_grad():
        output = model(torch.zeros(*input_shape))
    checks = {"output_shape": list(output.shape), "finite": bool(torch.isfinite(output).all().item())}
    for name, module in model.named_modules():
        if name.startswith("layer") and hasattr(module, "conv2"):
            block = module
            in_channels = block.conv1.in_channels
            residual_out = (
                block.downsample[0].out_channels if block.downsample is not None else in_channels
            )
            checks.setdefault("blocks", []).append(
                {
                    "block": name,
                    "conv1_in": int(block.conv1.in_channels),
                    "conv2_in": int(block.conv2.in_channels),
                    "conv3_in": int(block.conv3.in_channels),
                    "conv3_out": int(block.conv3.out_channels),
                    "residual_out": int(residual_out),
                    "residual_shape_ok": int(block.conv3.out_channels) == int(residual_out),
                }
            )
    checks["residual_shapes_consistent"] = all(item["residual_shape_ok"] for item in checks.get("blocks", []))
    return checks


# --------------------------------------------------------------------------- #
# export
# --------------------------------------------------------------------------- #
def _save_torchscript(traced, path: Path) -> None:
    """Save through an ASCII temp file.

    TorchScript's C++ writer converts whatever it receives with ``str(f)`` and
    then opens it as a narrow-character path, so a Chinese destination directory
    fails.  Writing to an ASCII temp path and moving the finished file with
    ``shutil`` keeps the Unicode path handling in Python.
    """
    import os
    import shutil
    import tempfile

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(suffix=".pt")
    os.close(handle)
    try:
        traced.save(temp_name)
        shutil.move(temp_name, str(path))
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)


def _load_torchscript(path: Path):
    """Load through an ASCII temp copy for the same Unicode-path reason."""
    import shutil
    import tempfile

    path = Path(path)
    with tempfile.TemporaryDirectory() as directory:
        temp_name = str(Path(directory) / "model.pt")
        shutil.copy2(str(path), temp_name)
        return torch.jit.load(temp_name, map_location="cpu")


def export_torchscript(
    model: nn.Module, path: Path, batch_size: int = 1, relax_determinism: bool = False
) -> dict:
    """torch.jit.trace only - no additional freeze or inference optimization."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    model = model.eval()
    example = torch.randn(batch_size, 3, 224, 224)
    with relaxed_determinism(relax_determinism), torch.no_grad():
        traced = torch.jit.trace(model, example)
    _save_torchscript(traced, path)
    return {
        "path": str(path),
        "method": "torch.jit.trace",
        "freeze": False,
        "inference_optimization": False,
        "trace_batch_size": batch_size,
        "bytes": int(path.stat().st_size),
    }


def verify_export(
    script_path: Path,
    eager_model: nn.Module,
    batch_sizes: tuple[int, ...] = (1, 8),
    atol: float = 1e-5,
    relax_determinism: bool = False,
) -> dict:
    """Reload the traced file and compare shapes/outputs against the eager model."""
    script_path = Path(script_path)
    loaded = _load_torchscript(script_path)
    loaded.eval()
    eager_model = eager_model.eval().to("cpu")
    checks = []
    for batch_size in batch_sizes:
        torch.manual_seed(1234 + batch_size)
        probe = torch.randn(batch_size, 3, 224, 224)
        with relaxed_determinism(relax_determinism), torch.no_grad():
            expected = eager_model(probe)
            actual = loaded(probe)
        difference = float((expected - actual).abs().max().item())
        checks.append(
            {
                "batch_size": int(batch_size),
                "expected_shape": list(expected.shape),
                "actual_shape": list(actual.shape),
                "shape_ok": list(expected.shape) == list(actual.shape),
                "max_abs_diff": difference,
                "consistent": difference <= atol,
            }
        )
    return {
        "path": str(script_path),
        "batch_checks": checks,
        "all_consistent": all(item["shape_ok"] and item["consistent"] for item in checks),
    }


def describe_model(model: nn.Module) -> dict:
    """Module type histogram, useful in reports."""
    counts: dict[str, int] = {}
    for _, module in model.named_modules():
        key = f"{type(module).__module__}.{type(module).__name__}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))

"""Build the experiment-3 report assets: comparison tables and figures.

Reads only the frozen artefacts written by run.py (evaluation summaries, timing
JSON, screening/selection JSON, metrics.csv) and writes
``runs/report/`` with CSV/Markdown tables and PNG figures.

No model is loaded and no new experiment is run here.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

EXP = Path(__file__).resolve().parent
RUNS = EXP / "runs"
OUT = RUNS / "report"
FIGS = OUT / "figures"

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
COLORS = {"A": "#4C72B0", "Q": "#DD8452", "P": "#55A868"}


def load(name: str):
    path = RUNS / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    FIGS.mkdir(parents=True, exist_ok=True)

    evaluation = load("evaluation/summary.json")
    freeze = load("frozen/freeze_report.json")
    screening = load("pruning/screening.json")
    selection = load("quantization/selection.json")
    if not evaluation or not freeze or not screening or not selection:
        raise SystemExit("missing evaluation/freeze/screening/selection artefacts")

    results = evaluation["results"]
    sizes = {name: info["bytes"] for name, info in freeze["exports"].items()}
    a_params = screening["a_parameters"]
    a_flops = screening["a_main_operator_flops"]
    pruning = {c["requested_ratio"]: c for c in screening["candidates"]}
    p_ratio = float(screening["selected_ratio"])
    p_candidate = pruning[p_ratio]

    # ---------------------------------------------------------------- tables --
    rows = []
    for key, value in results.items():
        device = key.rsplit(":", 1)[0]
        model = key.rsplit(":", 1)[1]
        rows.append(
            {
                "模型": model,
                "设备": device,
                "Top-1": round(value["top1"] * 100, 4),
                "Top-5": round(value["top5"] * 100, 4),
                "验证/测试 CE": round(value["ce"], 6),
                "宏Precision": round(value["macro_precision"] * 100, 4),
                "宏Recall": round(value["macro_recall"] * 100, 4),
                "宏F1": round(value["macro_f1"] * 100, 4),
                "参数": a_params if model != "P" else int(p_candidate["parameters"]),
                "主算子FLOPs": a_flops if model != "P" else int(p_candidate["main_operator_flops"]),
                "推理文件字节": sizes.get(model),
            }
        )
    with (OUT / "results_table.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    a_top1 = results["cpu:A"]["top1"]
    q_top1 = results["cpu:Q"]["top1"]
    p_top1 = results["cuda:0:P"]["top1"]

    markdown = [
        "# 实验三结果汇总（A / Q / P）",
        "",
        "## 测试集准确率（4,735 张，batch 1，每组合只评一次）",
        "",
        "| 模型 | 设备 | Top-1 | Top-5 | CE | 宏F1 | 参数 | 主算子FLOPs | 推理文件 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        markdown.append(
            f"| {row['模型']} | {row['设备']} | {row['Top-1']:.4f}% | {row['Top-5']:.4f}% | "
            f"{row['验证/测试 CE']:.4f} | {row['宏F1']:.4f}% | {row['参数']:,} | "
            f"{row['主算子FLOPs'] / 1e9:.4f} G | {row['推理文件字节'] / 1024 / 1024:.2f} MiB |"
        )
    markdown += [
        "",
        f"- Q 相对 A（CPU）：Top-1 {q_top1*100:.4f}% vs {a_top1*100:.4f}%，**{(q_top1-a_top1)*100:+.4f} pp**（目标 ≤2pp）",
        f"- P 相对 A（GPU）：Top-1 {p_top1*100:.4f}% vs {a_top1*100:.4f}%，**{(p_top1-a_top1)*100:+.4f} pp**（目标 ≤3pp）",
        f"- 文件体积：A {sizes['A']/1024/1024:.2f} MiB → Q {sizes['Q']/1024/1024:.2f} MiB "
        f"（{100*(1-sizes['Q']/sizes['A']):.2f}% 缩小）；P {sizes['P']/1024/1024:.2f} MiB "
        f"（{100*(1-sizes['P']/sizes['A']):.2f}% 缩小）",
        f"- 参数：P {int(p_candidate['parameters']):,}（{100*p_candidate['parameters']/a_params:.2f}% of A），"
        f"Q 逻辑参数沿用 A {a_params:,}",
        f"- 主算子 FLOPs：P {p_candidate['main_operator_flops']/1e9:.4f} G"
        f"（{p_candidate['main_operator_flops_drop']*100:.2f}% 下降），Q 逻辑 FLOPs 与 A 相同",
        "",
        "## 量化选型（激活上界 255，revision 2）",
        "",
        "| 校准量 | Top-1 | 相对 A | 是否达标 |",
        "|---|---|---|---|",
    ]
    for candidate in selection["candidates"]:
        markdown.append(
            f"| {candidate['calibration_images']} | {candidate['val_top1']*100:.4f}% | "
            f"{(candidate['val_top1']-selection['baseline_cpu']['top1'])*100:+.4f} pp | "
            f"{'是' if candidate['meets_target'] else '否'} |"
        )
    markdown += [
        "",
        "## 剪枝初筛（未微调，验证集）",
        "",
        "| 比例 | 通道保留率 | 参数 | 参数占A | 主算子FLOPs | FLOPs下降 | 未微调Top-1 |",
        "|---|---|---|---|---|---|---|",
    ]
    for ratio in (0.10, 0.20, 0.30):
        candidate = pruning[ratio]
        markdown.append(
            f"| {ratio:.0%} | {candidate['channel_keep_ratio']*100:.2f}% | {candidate['parameters']:,} | "
            f"{candidate['parameter_ratio']*100:.2f}% | {candidate['main_operator_flops']/1e9:.4f} G | "
            f"{candidate['main_operator_flops_drop']*100:.2f}% | {candidate['val_top1']*100:.4f}% |"
        )
    markdown += ["", f"选定比例：{p_ratio:.0%}（唯一满足 FLOPs 下降 ≥30% 的候选）", ""]

    timing = {}
    for path in sorted((RUNS / "timing").glob("*.json")):
        if path.name == "index.json":
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        timing[(payload["device"], payload["model"], payload["batch_size"])] = payload
    if timing:
        markdown += [
            "## 测速（模型推理，前 32 张验证图，预热 40 / 正式 100 × 3 轮）",
            "",
            "| 设备 | 模型 | batch | 中位数 ms | P95 ms | 吞吐 张/s（均值±标准差） |",
            "|---|---|---|---|---|---|",
        ]
        for (device, model, batch), payload in sorted(timing.items()):
            markdown.append(
                f"| {device} | {model} | {batch} | {payload['median_ms']:.2f} | {payload['p95_ms']:.2f} | "
                f"{payload['throughput_mean']:.2f} ± {payload['throughput_std']:.2f} |"
            )
        markdown.append("")
        markdown.append("口径：只计模型推理；不含读盘、预处理、HTTP 或网页时间。CPU 与 GPU 分别内部比较，不做跨设备宣称。")
        markdown.append("")
    (OUT / "results_summary.md").write_text("\n".join(markdown), encoding="utf-8")

    # --------------------------------------------------------------- figures --
    plt.figure(figsize=(6.4, 4.2))
    keys = ["cpu:A", "cpu:Q", "cuda:0:A", "cuda:0:P"]
    labels = ["A(CPU)", "Q(CPU)", "A(GPU)", "P(GPU)"]
    top1 = [results[key]["top1"] * 100 for key in keys]
    top5 = [results[key]["top5"] * 100 for key in keys]
    colors = [COLORS["A"], COLORS["Q"], COLORS["A"], COLORS["P"]]
    x = np.arange(len(keys))
    plt.bar(x - 0.19, top1, width=0.38, color=colors, label="Top-1")
    plt.bar(x + 0.19, top5, width=0.38, color=colors, alpha=0.45, label="Top-5")
    plt.axhline(a_top1 * 100 - 2, color="#C44E52", linestyle="--", linewidth=1, label="A−2pp（量化目标线）")
    plt.axhline(a_top1 * 100 - 3, color="#8172B3", linestyle=":", linewidth=1, label="A−3pp（剪枝目标线）")
    for index, value in enumerate(top1):
        plt.text(index - 0.19, value + 0.4, f"{value:.2f}", ha="center", fontsize=8)
    plt.xticks(x, labels)
    plt.ylim(68, 100)
    plt.ylabel("准确率（%）")
    plt.title("测试集准确率：A / Q / P（4,735 张）")
    plt.legend(fontsize=7)
    plt.tight_layout()
    plt.savefig(FIGS / "fig_accuracy.png", dpi=160)
    plt.close()

    fig, axes = plt.subplots(1, 3, figsize=(11, 3.6))
    names = ["A", "Q", "P"]
    size_mib = [sizes[name] / 1024 / 1024 for name in names]
    params = [a_params / 1e6, a_params / 1e6, p_candidate["parameters"] / 1e6]
    flops = [a_flops / 1e9, a_flops / 1e9, p_candidate["main_operator_flops"] / 1e9]
    for axis, values, title, unit in (
        (axes[0], size_mib, "推理文件体积", "MiB"),
        (axes[1], params, "参数量", "M"),
        (axes[2], flops, "主算子 FLOPs（Conv+Linear）", "GFLOPs"),
    ):
        bars = axis.bar(names, values, color=[COLORS[name] for name in names])
        axis.set_title(title, fontsize=10)
        axis.set_ylabel(unit)
        for bar, value in zip(bars, values):
            axis.text(bar.get_x() + bar.get_width() / 2, value * 1.01, f"{value:.1f}", ha="center", fontsize=8)
    axes[0].text(1, size_mib[1] * 1.25, f"−{100*(1-sizes['Q']/sizes['A']):.1f}%", ha="center", fontsize=8,
                 color="#C44E52")
    axes[1].text(2, params[2] * 1.35, f"−{100*(1-params[2]/params[0]):.1f}%", ha="center", fontsize=8,
                 color="#C44E52")
    axes[2].text(2, flops[2] * 1.35, f"−{100*(1-flops[2]/flops[0]):.1f}%", ha="center", fontsize=8,
                 color="#C44E52")
    axes[1].text(1, params[1] * 1.35, "Q 逻辑= A", ha="center", fontsize=7, color="#555555")
    axes[2].text(1, flops[1] * 1.35, "Q 逻辑= A", ha="center", fontsize=7, color="#555555")
    fig.suptitle("体积 / 参数量 / 计算量对比（Q 为逻辑值，量化只改存储与计算类型）", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIGS / "fig_size_params_flops.png", dpi=160)
    plt.close(fig)

    if timing:
        combos = [("cpu", 1), ("cpu", 8), ("cuda:0", 1), ("cuda:0", 8)]
        fig, axes = plt.subplots(2, 2, figsize=(9.5, 6.2))
        for axis, (device, batch) in zip(axes.ravel(), combos):
            models = ["A", "Q"] if device == "cpu" else ["A", "P"]
            medians = [timing[(device, model, batch)]["median_ms"] for model in models]
            p95 = [timing[(device, model, batch)]["p95_ms"] for model in models]
            bars = axis.bar(models, medians, color=[COLORS[model] for model in models],
                            yerr=[np.array(p95) - np.array(medians)], capsize=4)
            axis.set_title(f"{'CPU' if device == 'cpu' else 'GPU'} · batch {batch}", fontsize=10)
            axis.set_ylabel("单次推理时延（ms）")
            for bar, value, model in zip(bars, medians, models):
                throughput = timing[(device, model, batch)]["throughput_mean"]
                axis.text(bar.get_x() + bar.get_width() / 2, value * 0.5,
                          f"{value:.1f} ms\n{throughput:.1f} 张/s", ha="center", fontsize=8, color="white")
            ratio = medians[0] / medians[1]
            axis.text(0.5, 0.92, f"{models[1]} 比 {models[0]} 快 {ratio:.2f}×", transform=axis.transAxes,
                      ha="center", fontsize=8)
        fig.suptitle("同设备内推理速度对比（误差棒为 P95）", fontsize=11)
        fig.tight_layout()
        fig.savefig(FIGS / "fig_speed.png", dpi=160)
        plt.close(fig)

    metrics_path = RUNS / "finetune" / "metrics.csv"
    if metrics_path.is_file():
        with metrics_path.open(encoding="utf-8") as handle:
            records = list(csv.DictReader(handle))
        epochs = [int(row["epoch"]) for row in records]
        train_acc = [float(row["train_accuracy"]) * 100 for row in records]
        val_top1 = [float(row["val_top1"]) * 100 for row in records]
        val_ce = [float(row["val_ce"]) for row in records]
        lr = [float(row["lr_backbone"]) for row in records]
        fig, axes = plt.subplots(1, 3, figsize=(13, 3.8))
        axes[0].plot(epochs, train_acc, marker="o", markersize=3, label="训练集准确率")
        axes[0].plot(epochs, val_top1, marker="s", markersize=3, label="验证集 Top-1")
        axes[0].axhline(a_top1 * 100, color="#C44E52", linestyle="--", linewidth=1, label="A 验证 Top-1")
        axes[0].axhline(a_top1 * 100 - 3, color="#8172B3", linestyle=":", linewidth=1, label="A−3pp")
        best_epoch = int(np.argmax(val_top1))
        axes[0].annotate(f"最佳 {val_top1[best_epoch]:.2f}% @{epochs[best_epoch]}",
                         xy=(epochs[best_epoch], val_top1[best_epoch]),
                         xytext=(epochs[best_epoch] - 8, val_top1[best_epoch] + 4), fontsize=8,
                         arrowprops=dict(arrowstyle="->", lw=0.8))
        axes[0].set_xlabel("epoch")
        axes[0].set_ylabel("%")
        axes[0].set_title("微调：准确率", fontsize=10)
        axes[0].legend(fontsize=7)
        axes[1].plot(epochs, val_ce, marker="o", markersize=3, color="#4C72B0")
        axes[1].set_xlabel("epoch")
        axes[1].set_ylabel("验证集硬标签 CE")
        axes[1].set_title("微调：验证 CE（调度与停止依据）", fontsize=10)
        axes[2].plot(epochs, lr, marker="o", markersize=3, color="#55A868")
        axes[2].set_yscale("log")
        axes[2].set_xlabel("epoch")
        axes[2].set_ylabel("骨干学习率（log）")
        axes[2].set_title("学习率调度（ReduceLROnPlateau）", fontsize=10)
        fig.tight_layout()
        fig.savefig(FIGS / "fig_finetune_curve.png", dpi=160)
        plt.close(fig)

    ratios = [0.10, 0.20, 0.30]
    fig, axes = plt.subplots(1, 4, figsize=(13, 3.4))
    keep = [pruning[r]["channel_keep_ratio"] * 100 for r in ratios]
    drops = [pruning[r]["main_operator_flops_drop"] * 100 for r in ratios]
    unscreened = [pruning[r]["val_top1"] * 100 for r in ratios]
    params_ratio = [pruning[r]["parameter_ratio"] * 100 for r in ratios]
    for axis, values, title, threshold, unit in (
        (axes[0], keep, "通道保留率", 70.0, "%"),
        (axes[1], drops, "主算子 FLOPs 下降", 30.0, "%"),
        (axes[2], params_ratio, "参数占比（相对 A）", None, "%"),
        (axes[3], unscreened, "未微调验证 Top-1", None, "%"),
    ):
        bars = axis.bar([f"{r:.0%}" for r in ratios], values, color=["#4C72B0", "#DD8452", "#55A868"])
        if threshold is not None:
            axis.axhline(threshold, color="#C44E52", linestyle="--", linewidth=1)
        axis.set_title(title, fontsize=10)
        axis.set_xlabel("剪枝比例")
        axis.set_ylabel(unit)
        for bar, value in zip(bars, values):
            axis.text(bar.get_x() + bar.get_width() / 2, value + 1.5, f"{value:.1f}", ha="center", fontsize=8)
    axes[0].set_ylim(60, 100)
    fig.suptitle("三档剪枝初筛（红线 = 目标阈值；30% 档为唯一满足 FLOPs 目标的候选）", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIGS / "fig_pruning_screening.png", dpi=160)
    plt.close(fig)

    per_class_paths = {
        "A": RUNS / "evaluation" / "per_class_cuda0_A.csv",
        "P": RUNS / "evaluation" / "per_class_cuda0_P.csv",
    }
    if all(path.is_file() for path in per_class_paths.values()):
        data = {}
        for name, path in per_class_paths.items():
            with path.open(encoding="utf-8") as handle:
                data[name] = list(csv.DictReader(handle))
        errors_a = np.array([1.0 - float(row["recall"]) for row in data["A"]])
        errors_p = np.array([1.0 - float(row["recall"]) for row in data["P"]])
        order = np.argsort(-errors_a)[:40]
        matrix = np.vstack([errors_a[order], errors_p[order]]) * 100
        fig, axis = plt.subplots(figsize=(12, 3.4))
        image = axis.imshow(matrix, aspect="auto", cmap="Reds", vmin=0, vmax=max(10.0, matrix.max()))
        axis.set_yticks([0, 1])
        axis.set_yticklabels(["A(GPU)", "P(GPU)"])
        axis.set_xticks(range(len(order)))
        axis.set_xticklabels([data["A"][i]["class_name"].split(".")[0] for i in order], fontsize=6, rotation=90)
        axis.set_title("A 错误率最高的 40 个类别的逐类错误率（%，按 A 降序）", fontsize=10)
        fig.colorbar(image, ax=axis, fraction=0.02, pad=0.01)
        fig.tight_layout()
        fig.savefig(FIGS / "fig_class_error_heatmap.png", dpi=160)
        plt.close(fig)
        a_mean = float(np.mean(1 - np.array([float(row["recall"]) for row in data["A"]])))
        p_mean = float(np.mean(1 - np.array([float(row["recall"]) for row in data["P"]])))
    else:
        a_mean = p_mean = float("nan")

    payload = {
        "generated_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
        "note": "Report assets only. Reads frozen artefacts; runs no experiment.",
        "test_top1": {key: value["top1"] for key, value in results.items()},
        "delta_top1_pp": {"Q_cpu": (q_top1 - a_top1) * 100, "P_gpu": (p_top1 - a_top1) * 100},
        "sizes_bytes": sizes,
        "parameter_ratio_P": p_candidate["parameter_ratio"],
        "flops_drop_P": p_candidate["main_operator_flops_drop"],
        "mean_class_error": {"A": a_mean, "P": p_mean},
        "figures": sorted(path.name for path in FIGS.glob("*.png")),
    }
    (OUT / "report_assets.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                                           encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

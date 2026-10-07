# GitHub 文件与模型恢复说明

代码仓库为私有仓库 [gude206/herb-recognition-platform](https://github.com/gude206/herb-recognition-platform)。模型保存在同仓库的 [models-20261007 Release](https://github.com/gude206/herb-recognition-platform/releases/tag/models-20261007)，下载私有仓库及其 Release 需要具有仓库读取权限的 GitHub 账号。

源码、前端资源、CSV 图鉴、数据划分清单、实验指标和报告保存在代码仓库。完整原始图片数据集从作者固定版本恢复；代码中保留 300 张图鉴封面及 4 张识别示例所需的原路径图片，便于恢复模型后直接查看平台。依赖目录、虚拟环境、构建文件、本机日志与 API 密钥不属于上传内容。

## 新电脑安装与启动

需要 Windows PowerShell、Python（建议 3.11 或 3.12）、Git、Node.js 20 或更新版本。克隆仓库后，在仓库根目录执行：

```powershell
python -m venv TCMP-300/.venv-api
& .\TCMP-300\.venv-api\Scripts\python.exe -m pip install --upgrade pip
& .\TCMP-300\.venv-api\Scripts\python.exe -m pip install torch torchvision Pillow -r .\TCMP-300\requirements-api.txt
Push-Location .\数据标签
npm.cmd ci
Copy-Item -LiteralPath .env.example -Destination .env
Pop-Location
.\download-models.ps1
.\start-platform.ps1
```

安装步骤直接建立项目内的独立环境，不依赖原电脑的 `sxlwfx` 环境或 `D:\miniconda3`。上面的 PyTorch 安装可用于 CPU；需要 GPU 时，按 [PyTorch 安装页面](https://pytorch.org/get-started/locally/) 选择与本机 CUDA 兼容的安装命令。桌面 PyQt 界面另需 `pip install PyQt5`。

网页地址为 http://127.0.0.1:5173，接口文档为 http://127.0.0.1:8000/docs。停止平台执行 `./stop-platform.ps1`。图鉴使用 CSV，运行网页不需要 MySQL。

## 模型恢复

```powershell
# 默认只恢复网页 API 使用的基础版 best.pt（约 96.82 MB）
.\download-models.ps1

# 恢复全部 7 个模型文件（共 1,262,822,939 字节）
.\download-models.ps1 -All
```

`MODEL_MANIFEST.json` 记录每个原始相对路径、独立 Release 资源名、字节数和真实文件的 SHA-256。脚本通过 GitHub API 下载资源，先验证大小和 SHA-256，再写入原路径；已有同校验值文件会跳过，校验不同的文件会在新文件校验成功后被替换。下载到不完整临时文件时不会替换现有模型。

脚本优先读取当前会话的 `GH_TOKEN` 或 `GITHUB_TOKEN`，也可使用 Git Credential Manager 中 `gude206` 的 GitHub 登录凭据。凭据只在内存中使用，脚本不会输出凭据或写入配置文件。新电脑可先完成 GitHub 登录，再运行恢复命令。API 密钥与 GitHub 读取凭据分别管理。

| Release 资源 | 恢复位置 |
|---|---|
| resnet50_7030_baseline-best.pt | TCMP-300/runs/resnet50_7030_baseline/best.pt |
| resnet50_7030_baseline-last.pt | TCMP-300/runs/resnet50_7030_baseline/last.pt |
| resnet50_7030_ZQ-best.pt | TCMP-300/runs/resnet50_7030_ZQ/best.pt |
| resnet50_7030_ZQ-last.pt | TCMP-300/runs/resnet50_7030_ZQ/last.pt |
| resnet50_all300_old-best.pt | TCMP-300/runs/resnet50_all300_old/best.pt |
| resnet50_all300_old-last.pt | TCMP-300/runs/resnet50_all300_old/last.pt |
| imagenet-resnet50-11ad3fa6.pth | TCMP-300/weights/torch_hub/checkpoints/resnet50-11ad3fa6.pth |

当前 API 默认使用基础版第 19 轮的 `best.pt`。其他权重可通过 `TCMP_CHECKPOINT` 指定。`last.pt` 包含续训状态；历史 `resnet50_all300_old` 使用过完整原始验证集，不适合作为重新划分后独立测试的模型。训练脚本会通过 Torchvision 自动下载缺失的 ImageNet 预训练缓存，因此只运行默认网页时无需恢复该缓存。

已有评估 JSON 记录原电脑的检查点绝对路径；API 在新目录启动时可能不展示实验准确率。模型识别不受影响，完整评估结果仍在 `runs/` 的记录文件中。

## 完整图片数据集恢复

作者原项目为 [winycg/TCMP-300](https://github.com/winycg/TCMP-300)，论文数据引用为 [10.6084/m9.figshare.29432726](https://doi.org/10.6084/m9.figshare.29432726)。使用作者团队 [anzhulin/tcmp-300](https://huggingface.co/datasets/anzhulin/tcmp-300) 的固定版本 `7613f038f48e3ecc84076913a2f3bcd52599b0f2`，原有核验见 `TCMP-300/data/author_tcmp_300/VERIFICATION.md`。

```powershell
# 下载、校验并解压；默认保留压缩包，便于断续操作和后续复用
.\download-data.ps1

# 下载/校验并成功解压后删除压缩包，节省空间
.\download-data.ps1 -RemoveArchive
```

固定压缩包 `tcmp-300-release.tar.gz` 为 **12,820,492,346 字节**，SHA-256 为 `f3d32fb003cccf817c735aaa0978a5381058aa77ec5d410a818b720b048d5739`。脚本在 `.downloads/` 保留通过校验的压缩包，列出并检查路径后，只提取压缩包的 `tcmp-300/` 子目录到 `TCMP-300/data/author_tcmp_300/images/`。固定版本的根目录还包含 macOS 元数据，根级元数据不会提取。压缩包目录结构已通过少量流式读取确认。

完整解压数据约 13.01 GB，共 52,172 个文件（83 个 GIF，非 GIF 图片 52,089 张）。下载与解压同时存在时，建议至少预留 **27 GB** 空间。路径检查需要完整读取压缩包，解压也需再次读取，时间取决于磁盘性能。下载失败的临时文件会清理，下次运行重新下载；已有完整、通过校验的压缩包可复用。完整数据用于重新训练、测试和增强预览；仅使用网页识别与已保留参考图时无需下载完整数据集。

数据集图片与资料保留作者来源及既有审核/授权状态，不把未人工核对的参考图或植物身份当作已确认结论。

## 本机 API 密钥

DeepSeek 问答只在本机 `TCMP-300/.env` 配置。新电脑执行下面的复制命令，再用本机编辑器填写 `DEEPSEEK_API_KEY`：

```powershell
Copy-Item -LiteralPath .\TCMP-300\.env.example -Destination .\TCMP-300\.env
```

`.env` 已忽略，不会随 Git 上传。仓库只保留不含真实密钥的 `.env.example`。请勿把密钥写进源码、README、前端环境变量或 Release 附件。没有配置密钥时，图片识别和图鉴仍可正常使用；问答会提示未配置。

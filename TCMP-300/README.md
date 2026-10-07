# TCMP-300 ResNet50 训练与在线增强对比

本项目使用 [TCMP-300 原项目](https://github.com/winycg/TCMP-300) 的作者数据集，对 ImageNet 预训练的 ResNet50 进行 300 类植物图像分类微调。数据来源与校验记录见 [VERIFICATION.md](data/author_tcmp_300/VERIFICATION.md)。

## 文件

- `train_resnet50.py`：无随机数据增强的基础版；训练和验证均使用固定缩放、中心裁切与归一化。
- `train_resnet50_ZQ.py`：在线增强版；训练图片每次读取时随机裁切、水平/垂直翻转、旋转及调整亮度、对比度、饱和度和色相。验证预处理与基础版相同。
- `augmentation_preview.ipynb`：使用指定的 `001.Veronica persica Poir` 图片展示各项增强效果和组合采样，不加载或训练模型。
- `augmentation_preview_ZQ.png`：Notebook 生成的四列组合增强预览。
- `app.py`：PyQt5 图片识别界面，从 `tcmp-info-20250329.csv` 读取对应中文名。
- `data/author_tcmp_300/images/tcmp-300/train`：训练集，36,324 张图片。
- `data/author_tcmp_300/images/tcmp-300/val`：作者原始验证目录，15,765 张可用于 PyTorch 的图片；原文件保持不动。
- `data/author_tcmp_300/splits/val.csv`、`test.csv`：固定分层划分清单，分别为 11,030 张验证图片和 4,735 张测试图片。
- `make_splits.py`：用固定种子 `20260927` 重新生成并核对划分清单。
- `evaluate_test.py`：用最终选定的模型评估保留的测试集。
- `weights/torch_hub`：PyTorch 缓存的 ImageNet 预训练权重。
- `runs/resnet50_all300_old/`：使用完整原始验证集选择过权重的历史结果，不能作为新划分的独立测试结果。
- `runs/resnet50_7030_baseline/`：新基础版的默认输出目录。
- `runs/resnet50_7030_ZQ/`：新在线增强版的默认输出目录。

## 运行两版训练

在 Windows PowerShell 中，使用本机已有的 `sxlwfx` 环境；下面两条命令分别从相同的 ImageNet 预训练权重开始训练，共用固定的 70/30 验证/测试划分、训练参数和随机种子 `42`。测试清单不会在训练和早停时加载为数据集：

```powershell
cd 'D:\Study\AI全栈开发\TCMP-300'
& 'D:\miniconda3\envs\sxlwfx\python.exe' .\train_resnet50.py --epochs 20
& 'D:\miniconda3\envs\sxlwfx\python.exe' .\train_resnet50_ZQ.py --epochs 20
```

每个目录会保存 `best.pt`、`last.pt` 和 `metrics.csv`。如果中断，在对应命令后加 `--resume`，并把 `--epochs` 设为大于检查点轮次的总轮数。新检查点记录增强模式、划分指纹、参数、软件版本及 Python/NumPy/Torch/CUDA/DataLoader 随机状态。训练增强按轮次与样本种子生成，不受 persistent worker 生命周期影响。为避免覆盖旧指标，从头训练时若目标目录已有结果，脚本会要求换一个 `--output-dir`。

需要相同软硬件上的轮次边界精确续训时，首次训练和恢复均加 `--deterministic`，并保持 seed、batch_size、accumulation 等参数一致。增加总轮数会保留检查点的原余弦调度，不等价于以新总轮数重新训练。旧检查点仍可恢复，但会提示无法还原当时未保存的随机状态；新记录不能追溯修复旧实验。

两版均已完成 20 轮训练，并保存权重与独立测试结果。基础版测试 Top-1 为 79.85%、Top-5 为 92.29%；增强版分别为 80.00%、92.82%。训练需要 `torch`、`torchvision` 和 `Pillow`；Notebook 还需要 `IPython`。

## 与 React 前端连接

`api.py` 提供真实识别接口，默认使用与桌面程序相同的 `runs/resnet50_7030_baseline/best.pt`（第 19 轮），在启动时加载一次，优先使用 CUDA，未提供 GPU 时使用 CPU。

首次安装（项目内独立虚拟环境，复用现有模型依赖）：

```powershell
cd 'D:\Study\AI全栈开发\TCMP-300'
& 'D:\miniconda3\envs\sxlwfx\python.exe' -m venv --system-site-packages .venv-api
& '.\.venv-api\Scripts\python.exe' -m pip install -r requirements-api.txt
.\start-api.ps1
```

安装后可以在父目录运行 `./start-platform.ps1`，同时启动前后端，并等待模型健康检查和页面均就绪。网页为 http://127.0.0.1:5173 ，接口文档为 http://127.0.0.1:8000/docs 。执行 `./stop-platform.ps1` 停止状态文件记录的本次实例；启动失败自动清理本次进程。后台日志分别位于前端目录 `frontend.<端口>*.log` 和当前目录 `api.<端口>*.log`，已有端口不会被强制清理。自定义 `-ApiPort`、`-FrontendPort` 时，脚本同步设置前端接口地址与仅本地可用的 CORS 来源。

- `GET /api/v1/health`：加载状态与模型指标。
- `POST /api/v1/predict`：multipart 字段 `file`，返回 `prediction`、5 条按置信度降序排列的 `top_k` 和 `model`。
- `GET /api/v1/recognition/samples`：四张真实训练集示例，图片通过 `/api/v1/recognition/samples/{id}/image` 提供。
- GET /api/v1/herbs：读取主 CSV 的 300 类植物，支持 q/family/genus/region/effect/property/part/sort/page/page_size；默认每页 24 条，最多 60 条。
- GET /api/v1/herbs/filters：真实科属、分布地区与药材筛选选项。
- GET /api/v1/herbs/{id}：活体身份、分布、生境、器官特征、独立药材记录、来源与审核状态。
- GET /api/v1/herbs/{id}/reference-image：经目录边界检查的本地数据集参考图。网页标注待核对，不作为已核实器官图。

图鉴适配器 herb_catalog.py 只读 data/author_tcmp_300/tcmp-info-20250329.csv，不修改原 CSV 或现有 MySQL 表。文件发生变化时重读缓存。使用 tcmp-001 至 tcmp-300 对接模型预测；身份冲突、未人工审核和字段缺口原样保留。地区筛选按来源文字匹配，药用部位筛选提取器官名称，药材完整原文保留在详情中。前端 /herbs 默认使用这些真实接口。

图鉴验证：.venv-api\Scripts\python.exe -m unittest test_catalog test_api -v，覆盖 300 类分页、搜索和组合筛选、来源及药材一致性、身份冲突、图片目录边界和原识别接口。

预测返回稳定类别 ID `tcmp-001` 等、中文名、学名、科属和 softmax 分数，并提供 `identity_conflict`、`identity_status`、`review_status`、`original_latin_name`、`accepted_latin_name`。第 51 类保留原始类别，规范学名为空并明确标识冲突，不把候选学名作为确认身份。

预处理与验证阶段保持一致，并处理 EXIF 方向、RGB 转换和无效图片。限制为一个名为 `file` 的 JPG/PNG/WEBP 文件、10MiB、2500 万原始像素、最长边 10000 像素、最长/最短边比例不超过 20，并要求 Resize 后预计像素不超过 100 万（最终限制可能更严格）。整个请求体在 multipart 解析前按实际接收字节限制为 10MiB 加 64KiB 开销，含缺少长度头或 chunked 的请求。大于 1MiB 的请求会使用有界临时文件，请求结束或取消时关闭；上传内容不写入数据集。

结果中的测试指标读取当前检查点旁的 `test_evaluation/test_metrics.json`，并核对检查点路径、轮次和数据划分指纹。单张图片的 Top 5 置信度与整个测试集的 Top-5 准确率分别显示。

如需选择其他已有权重，在启动后端前设置 `$env:TCMP_CHECKPOINT` 为其绝对路径；服务不会自动切换模型。

验证接口：

```powershell
& '.\.venv-api\Scripts\python.exe' -m unittest test_api -v
```

测试使用真实模型，覆盖保留测试图片、预测类别排序、真实示例、空/伪造/过大上传、灰度/透明 PNG、格式限制和浏览器跨域。

## DeepSeek 大模型问答

首页 AI 助手调用 `POST /api/v1/chat`，由 `deepseek_chat.py` 请求 DeepSeek 的兼容接口。安装更新后的后端依赖：

```powershell
& '.\.venv-api\Scripts\python.exe' -m pip install -r requirements-api.txt
```

配置文件位于当前目录 `.env`（已创建）；新环境可复制 `.env.example` 为 `.env`。填写以下参数：

```dotenv
DEEPSEEK_API_KEY=你的DeepSeek密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_TEMPERATURE=0.3
DEEPSEEK_MAX_TOKENS=1024
DEEPSEEK_TIMEOUT_SECONDS=60
```

在 [DeepSeek 开放平台](https://platform.deepseek.com/) 创建密钥，填入 `DEEPSEEK_API_KEY`；`.env` 已列入 Git 忽略。地址填写到域名或 `/v1` 即可，代码自动追加 `/chat/completions`。模型可改为账户支持的模型，如 `deepseek-reasoner`；使用推理模型时建议将超时增加至 120 或 180 秒，生成上限按需要增加至最多 8192。temperature 范围 0~2，是否生效由所选模型决定。

后端每次请求重读 `.env`，参数改完直接再次提问即可；系统进程环境中同名参数会覆盖文件。首次更新代码需重启后端。密钥不进入前端配置或响应；缺少密钥时仍能正常使用图片识别和图鉴，问答返回明确的未配置提示。

接口接受最多 2000 字的问题，可选 `herb_id` 和最近 12 条 user/assistant 历史。图鉴上下文读取真实 CSV，保留身份冲突与审核状态；不传原图片。历史由前端携带，后端不保存对话。回答为完整文本，当前不使用流式输出；图鉴上下文参考条目不等于模型已核验引文。

验证：`.venv-api\Scripts\python.exe -m unittest test_chat -v`。测试用模拟 DeepSeek HTTP 响应验证消息上下文、参数热更新、输入校验和错误处理，不产生 API 费用；真实服务仍需有效密钥和余额。

## 最终测试

先用新验证集比较增强方案和选择检查点；确定方案后，再对预先指定的模型运行测试，例如：

```powershell
& 'D:\miniconda3\envs\sxlwfx\python.exe' .\evaluate_test.py .\runs\resnet50_7030_ZQ\best.pt
```

脚本会输出 Top-1、Top-5、平均损失和宏平均 Precision/Recall/F1，并在检查点旁的 `test_evaluation/` 保存 `test_metrics.json`、300 类的 `per_class.csv` 与 `per_image.csv`。逐图结果包含相对路径、真值、Top-1/Top-5 类别及分数、图片内容 SHA-256；元数据记录模型、图片集合与结果文件指纹。可用 `--output-dir` 保留旧评估目录。

两版已冻结模型的新逐图评估保存在各自 `paired_test_evaluation/`。运行以下命令可生成经过路径、真值与内容一致性校验的配对比较：

```powershell
& '.\.venv-api\Scripts\python.exe' .\compare_predictions.py .\runs\resnet50_7030_baseline\paired_test_evaluation .\runs\resnet50_7030_ZQ\paired_test_evaluation --output-dir .\runs\paired_baseline_ZQ
```

报告保存配对图像 bootstrap 的 95% 差异区间与精确双侧 McNemar 检验。基础版和增强版的单次 Top-1 差异仅 7 张图片，不能据此断言增强稳定更好；配对比较也不衡量不同训练种子的波动。图片具有同源相关性时应另用来源分组分析，不在保留测试集上反复调参。

回归检查：`.venv-api\Scripts\python.exe -m unittest test_api test_catalog test_upload_limits test_chat test_training_tools -v`。训练工具检查使用小型随机数据验证轮次恢复序列与模型更新、持久 worker 增强和错误配对拒绝，不执行整套 ResNet50 训练。

不要用测试结果反复调整增强参数或早停轮次。历史 `runs/resnet50_all300_old/best.pt` 已用完整原始验证集选过权重，测试脚本会拒绝把它当作新划分的独立测试模型。
历史完整验证集上的准确率与新划分上的验证准确率也不能直接比较；消融对比应以这次重新训练的两版结果为准。

## 查看增强图

打开 `augmentation_preview.ipynb` 即可直接查看已保存的图；重新逐单元运行会用同一张图片再次生成图，并更新 `augmentation_preview_ZQ.png`。

## 图片识别界面

```powershell
cd 'D:\Study\AI全栈开发\TCMP-300'
& 'D:\miniconda3\envs\sxlwfx\python.exe' .\app.py
```

选择图片并点击“开始识别”，界面会显示中文预测名和前 3 类分数。界面还需要 `PyQt5`；若环境中缺少，执行 `python -m pip install PyQt5`。

在新基础版尚未产出 `best.pt` 时，界面会回退使用 `runs/resnet50_all300_old/best.pt`；基础版完成后默认使用 `runs/resnet50_7030_baseline/best.pt`。

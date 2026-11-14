# 中草药识别与知识平台

GitHub 仓库与模型下载、跨电脑安装和完整数据恢复说明见 [GITHUB_UPLOAD.md](GITHUB_UPLOAD.md)。原模型和实验三 INT8 模型权重保存在 Releases，API 密钥仅在本地 `.env` 配置。

本目录包含 React 前端 `数据标签/`、模型与 FastAPI 后端 `TCMP-300/`，以及独立本地 MySQL 实例 `mysql-local/`。植物图鉴、科普文章、AI 对话和图片识别历史统一使用 MySQL；配置、表结构、身份范围与安装步骤见 [MYSQL_HISTORY.md](MYSQL_HISTORY.md)。原始 CSV 和文章种子文件保留用于导入及校验。识别默认使用实验三 CPU INT8 模型，亦支持原 ResNet50 权重，问答与数据库凭据配置在后端 `.env`。

实验四本次模型接入、接口说明及网页耗时结果见 [实验四记录](experiment4/实验四记录.md)。

实验五已新增 LangChain Agent、工具调用、图片对话和文本分类；实现与数据说明见 [实验五记录](experiment5/README.md)，验收及暂缓事项见 [执行清单](experiment5/TASKS.md)。基座下载取消，云端训练与成员分工暂缓；队列真实部署和独立浏览器验收尚未完成。

## 启动与停止

本机已配置好依赖，直接双击项目根目录的 **`一键启动.bat`**：自动启动项目 MySQL、后端和前端，健康检查通过后打开首页；默认端口被占用时自动选择空闲端口，窗口显示实际网址。项目已正常运行时再次双击会直接打开首页。关闭启动窗口不会停止服务；需要停止前后端及本项目的独立 MySQL 时，双击 **`一键关闭.bat`**，数据会保留。失败时窗口保留错误提示，便于查看原因。这两个入口使用 Windows 自带的 PowerShell，不需要安装 PowerShell 7。

首次使用按两个项目的 README 安装依赖。在当前目录执行：

```powershell
.\start-platform.ps1
.\stop-platform.ps1
```

启动脚本等待模型健康检查和前端页面均通过后，才报告就绪。默认网页地址为 http://127.0.0.1:5173，接口文档为 http://127.0.0.1:8000/docs。启动失败会清理本次创建的进程；已占用的端口不会被强制释放。

成功启动会保存 `.platform-processes.json`。停止脚本核对进程 ID、启动时间、程序路径和项目命令行，只停止记录的本次实例及其子进程。旧脚本或手动创建的实例不会自动被纳入这个状态文件。

可指定独立端口和状态文件；前端接口地址及后端本地 CORS 来源由启动脚本同步配置：

```powershell
.\start-platform.ps1 -ApiPort 8100 -FrontendPort 5273 -StateFile .\.platform-demo.json
.\stop-platform.ps1 -StateFile .\.platform-demo.json
```

日志为 `TCMP-300/api.<端口>.log`、`api.<端口>.err.log` 和 `数据标签/frontend.<端口>.log`、`frontend.<端口>.err.log`。模型加载等待时间默认 90 秒，可使用 `-StartupTimeoutSeconds` 调整。

## 当前行为

- 图片只允许 JPG、PNG、WEBP，一个名为 `file` 的上传文件，最多 10MiB；解析前还限制整个请求体为 10MiB 加 64KiB multipart 开销。总像素、最长边、长宽比和缩放后的预计像素均有限制。
- 识别结果标为模型候选，并保留图鉴的审核与身份状态。第 51 类维持原始模型类别映射，明确提示身份冲突，不把候选学名当成已确认物种。
- 图鉴关键词包含名称、学名、别名、药材名与传统功效，最多 200 字；参数错误、超时与断网分别显示。
- MySQL 保留模型 300 类的全部 103 个原始字段；公开图鉴只展示 299 条有来源的植物资料。未核验药用、毒性、混淆资料及未获授权的参考图片不再公开或用于 AI 植物上下文。7 篇未审核课程示例保留为后台草稿；文章发布需审核完成并提供公开来源。详见 [CONTENT_PUBLICATION.md](CONTENT_PUBLICATION.md)。
- 首页问答支持右上角的历史对话和新对话入口；可按问题、回答和植物名称搜索，选中记录后继续追问。同一植物可建立多个独立对话，成功问答保存到 MySQL。
- `/login` 提供真实用户注册、用户登录和管理员登录。登录后 AI 问答及图片识别历史归属账号，可在其他浏览器登录查看；登录或注册时可选择关联当前访客记录。管理员可在 `/admin/articles` 新增、编辑、上传封面、发布、移入回收站和恢复文章。账号使用说明及本机管理员凭据位置见 [AUTH_ACCOUNTS.md](AUTH_ACCOUNTS.md)。
- 成功图片识别自动保存原图和结果，草药识别卡片右上角可打开识别历史，按植物名称或文件名搜索并恢复查看；原图保存在本地上传目录，数据库保存路径和结果。
- 从图鉴进入详情，再返回会保留关键词、筛选、排序和分页。直接打开详情时返回默认图鉴。
- 已移除的看板、关于页与专属资源保存在 `数据标签/archive/`。当前 Vite 命令显式读取 TypeScript 配置，生成文件位于 `.build/`。

## 验证与实验

```powershell
Push-Location .\数据标签
npm.cmd test
npm.cmd run build
Pop-Location

Push-Location .\TCMP-300
.\.venv-api\Scripts\python.exe -m unittest test_api test_catalog test_upload_limits test_chat test_training_tools -v
Pop-Location

.\test-platform.ps1
```

平台检查默认在 8100/5273 与 8101/5274 端口启动隔离实例，验证真实模型就绪、启动失败回滚、重复启动保护和停止清理；测试结束会停止这些实例。

训练新增 `--deterministic`、随机状态保存与按轮次/样本确定的增强种子。精确续训限于新的轮次边界检查点、相同参数和相同软硬件；旧检查点仍支持续训，但会提示缺少原始随机状态。

评估现在保存带图片内容 SHA-256 的逐图 Top-1/Top-5 结果。`compare_predictions.py` 先核对两份结果的图片、真值、类别和划分指纹，再计算配对 bootstrap 区间与 McNemar 检验。两版固定模型的结果位于各自 `paired_test_evaluation/`，比较报告位于 `TCMP-300/runs/paired_baseline_ZQ/`。比较用于描述已冻结模型，不用于在测试集上调整训练方案。

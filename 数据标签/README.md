# 中草药智能识别与知识平台

基于 React、TypeScript、Vite 的植物识别与本草知识平台。图片识别连接相邻 TCMP-300 项目的 ResNet50；草药图鉴读取同项目的真实 CSV，共 300 个稳定模型类别。AI 问答由后端连接 DeepSeek，登录和科普文章仍保留课程演示数据。

## 本地查看

在父目录 D:\Study\AI全栈开发 中执行 ./start-platform.ps1，脚本等待前后端健康检查通过后报告就绪。打开 http://127.0.0.1:5173/herbs 浏览图鉴，或打开首页上传植物图片。接口文档为 http://127.0.0.1:8000/docs 。执行 ./stop-platform.ps1 可停止本脚本记录的实例；启动失败会清理本次进程。

也可以分别运行 ../TCMP-300/start-api.ps1 和 npm run dev -- --host 127.0.0.1 --port 5173 --strictPort。不要重复启动已占用端口的服务。

## 图鉴数据

主文件为 ../TCMP-300/data/author_tcmp_300/tcmp-info-20250329.csv。后端只读 CSV，按文件变化刷新缓存；本次网页不另建库，不修改现有 MySQL 数据。CSV 的植物ID tcmp-001 至 tcmp-300 与识别结果一致。

图鉴支持名称、学名、别名、药材名和传统功效搜索，关键词最多 200 字；参数错误、超时、断网分别提示。支持科、属、分布地区筛选，药材功效、药性与器官部位筛选，24 条分页、名称排序、最近浏览优先和网格/列表切换。从图鉴进入详情后，返回会保留筛选、排序与分页。地区选项按来源分布文字匹配，不属于完整地理编码或定位判断。

详情按活体植物展示身份、分布、生境、海拔、花果/孢子期和器官特征，并独立列出药材的基原、部位、加工、性味和传统记载。来源链接、资料版本、字段缺口和审核状态可追溯。原资料中文科属保留原分类体系，可能与规范科属不同。

当前 299 类有分布资料。tcmp-051 的原中文名、学名与分类冲突，在详情中特别提示。所有条目仍未人工审核；无毒性记载不代表无毒。图片由本地数据集提供，统一标注“数据集参考图 · 待核对”，尚未核实器官及授权状态。空字段显示“暂无可靠资料”，不会补成鉴定结论。

## 配置与构建

需要 Node.js 20 或更新版本。安装依赖后执行 npm run dev；生产构建执行 npm run build；状态与导航检查执行 npm test。Vite 命令显式读取 vite.config.ts，配置编译输出保存在 .build/。退出当前路由的看板、关于页及其专属资源归档在 archive/，ECharts 已从当前依赖中移除。

复制 .env.example 为 .env。默认配置：

    VITE_API_BASE_URL=http://127.0.0.1:8000
    VITE_USE_MOCK=true
    VITE_MOCK_RECOGNITION=false
    VITE_MOCK_HERBS=false

图鉴和识别分别由 VITE_MOCK_HERBS、VITE_MOCK_RECOGNITION 控制，不依赖总演示开关。将图鉴开关设为 true 可浏览 16 条离线示例，其总数不会显示为真实 300 类。其他业务保留 VITE_USE_MOCK=true。修改环境变量后重启 Vite。

## DeepSeek 问答配置

编辑相邻后端的 `../TCMP-300/.env`，在 `DEEPSEEK_API_KEY=` 后填入密钥。接口地址、模型、temperature、生成 token 上限和超时均在该文件中；完整参数说明见后端 `.env.example`。首次安装需执行后端的 `pip install -r requirements-api.txt` 并启动 `start-api.ps1`。

后端每次问答读取配置，修改 `.env` 后下一次问答即生效；进程环境中同名变量优先。密钥只留在后端，不放进前端 `VITE_*` 配置。问答不受 `VITE_USE_MOCK` 控制，不会用模拟回复替代请求失败。

首页助手按植物类别分别保存连续追问，每次仅携带当前植物最近 6 轮成功对话；当前参考植物会显示在助手上方。处理中切换植物时，旧回答仍写回原植物会话。会话在页面内存中保存，刷新或离开首页后清空。识别成功后会附带对应图鉴资料（包括审核状态）供模型参考，不会上传原图片。缺少密钥、余额不足、限流或超时会在助手中显示具体提示。当前采用一次返回完整回答，不是流式输出。

## 页面与接口

- /：真实图片识别、前五项预测与植物详情入口、来源知识卡片和最近浏览。
- /herbs、/herbs/:id：真实植物列表及详情。
- /knowledge、/login：课程演示业务。
- 全局搜索提交至 /herbs?q=关键词；最近浏览只存于本机浏览器。

| 服务 | 路径 |
|---|---|
| 图鉴列表 | GET /api/v1/herbs |
| 真实筛选选项 | GET /api/v1/herbs/filters |
| 植物详情 | GET /api/v1/herbs/{id} |
| 本地参考图 | GET /api/v1/herbs/{id}/reference-image |
| 图片识别 | POST /api/v1/predict，multipart 字段 file |
| 识别示例 | GET /api/v1/recognition/samples |
| DeepSeek 问答 | POST /api/v1/chat，JSON 包含 message、可选 herb_id 和 history |

识别支持 JPG、PNG、WEBP，最大 10MiB；原始图片最长边不超过 10000 像素、总像素不超过 2500 万，缩放后预计像素不超过 100 万，极端长宽比会要求裁剪。单张图片的置信度是模型分数，不等于识别准确率；分布信息不会用于排除模型预测。识别页面保留前五项置信度、候选身份与审核提示，第 51 类明确显示身份冲突。上传预览与结果图片完整显示原比例，更换图片按钮位于预览下方。数据看板与关于项目已从路由、导航和首页入口移除。

测试后端：在 TCMP-300 目录执行 .venv-api\Scripts\python.exe -m unittest test_catalog test_api -v 。测试使用真实 CSV、参考图片及识别模型。

本平台用于植物识别与传统本草知识学习，不提供在线诊断、处方或剂量建议。

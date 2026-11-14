# MySQL 平台资料与历史记录

平台使用真实 MySQL 保存植物图鉴、科普文章、成功问答与成功识别记录。科普页面和图鉴页面通过后端读取资料；历史入口读取对应记录，可继续问答或回看图片与前五个模型候选。

## 当前本机配置

- 独立实例：`127.0.0.1:3307`，仅监听本机，不注册或修改现有 Windows MySQL 服务。
- 数据库：`herb_platform`。应用账号：`herb_app`，仅有本库的 SELECT、INSERT、UPDATE 权限。
- 连接密码和 DeepSeek 密钥保存在 `TCMP-300/.env`；管理凭据保存在 `mysql-local/.admin.env`。这些文件均被 Git 忽略。
- MySQL 实际数据目录：`mysql-local/data/`。上传图片：`TCMP-300/uploads/recognition/`。两者均不上传 GitHub。
- Windows MySQL 8.4 使用临时目录中的 ASCII 目录联接访问中文项目路径；实际数据仍在项目内，启动时会校验并按需恢复这个路径别名。redo 和 undo 目录显式指定绝对 ASCII 路径，避免默认相对路径在日志轮转时重新解析为中文路径。配置项说明见 [MySQL 官方文档](https://dev.mysql.com/doc/refman/8.4/en/innodb-parameters.html)。

## 表与保存时机

| 表 | 内容 |
|---|---|
| `history_owners` | 访客令牌摘要、账号历史归属及一次性关联标记，后端不保存原始访客令牌 |
| `app_users` | 用户名、昵称、Argon2id 密码摘要、用户或管理员角色 |
| `auth_sessions` | 登录令牌摘要、归属账号、过期与撤销时间 |
| `auth_attempts` | 登录和注册频率限制计数，不保存密码 |
| `chat_conversations` | 对话标题、植物参考、创建与更新时间 |
| `chat_messages` | 完整问题和回答、顺序、模型名称与资料引用 |
| `recognition_records` | 原文件名、原图路径与 SHA-256、前五个候选、模型信息、识别时间 |
| `plant_catalog` | 300 个稳定类别、常用名称分类与审核索引字段、全部 103 个原始字段的 JSON、原始源文件 SHA-256 |
| `science_articles` | 标题、分类、摘要、正文、封面路径、发布和审核状态、来源说明、排序、版本与回收站时间 |
| `article_audit_log` | 文章操作人、操作时间以及修改前后快照 |
| `content_imports` | 植物和文章的首次导入来源指纹、数量及时间 |

问答从数据库获取最近六轮上下文，忽略客户端声称的历史；成功得到回答后，问题与回答在同一个事务中提交。失败时不会写入半条问答，同一对话的并发请求会被拒绝。识别结果和图片写入失败时清理本次图片，避免残留无关联文件。数据库不可用时明确返回错误，不宣称保存成功。

已有访客浏览器问答会自动、幂等地导入 MySQL，不覆盖后端已有的新消息。访客保留原本本地缓存；登录账号的完整消息只在数据库及页面内存中，sessionStorage 仅保存选择和草稿，退出时清理该账号的草稿。后端记录是成功问答的权威来源。

## 图鉴与文章资料

图鉴原始文件为 `TCMP-300/data/author_tcmp_300/tcmp-info-20250329.csv`。`plant_catalog.source_payload` 完整保存全部字段，包括药材记录、证据与来源、规范分类、图片候选路径、审核与冲突状态；不修改 CSV，也不改变原始模型类别 ID 和学名。图鉴列表、详情、筛选、AI 参考资料与模型加载时的标签校验读取 MySQL，数据库读取缓存最多一秒。

文章种子为 `TCMP-300/data/knowledge/articles.seed.json`，从原项目 7 篇课程演示文章迁移，标记 `course_example` 和“未审核”。原示例阅读量仅存为 `legacy_read_label` 供追溯，真实 `read_count` 初始为 0，当前未增加浏览统计功能。页面以“推荐阅读”展示示例，不宣称这些数值是真实阅读量。文章封面仍使用原来缺失图片的占位图，文件位于 `TCMP-300/assets/articles/`，数据库保存相对路径。

只有已发布、已审核、包含公开来源且不含待核验内容的正式科普文章可公开读取。现有 7 篇课程示例已转为草稿，原文保留；原始植物资料完整留存，公开页面只采用当前可追溯的来源字段。内容规则见 [CONTENT_PUBLICATION.md](CONTENT_PUBLICATION.md)。重新执行导入仅补充缺少的 ID，不覆盖数据库中已有的编辑内容。现有数据库升级可运行：

```powershell
.\start-mysql.ps1
& .\TCMP-300\.venv-api\Scripts\python.exe .\TCMP-300\tools\import_content_mysql.py
```

导入报告保存在被 Git 忽略的 `mysql-local/content-import-report.json`，记录源文件指纹、导入数量及保持不变的历史记录数量。启用 MySQL 时读取失败会明确报错；仅在 `MYSQL_ENABLED=false` 的兼容模式下使用原 CSV 与文章种子，不在错误发生时静默回退。

## 身份范围

当前已接入真实账号：注册只创建普通用户；管理员通过本机初始化工具创建。登录后，问答和图片识别记录归属账号，同一账号可在其他浏览器登录后查看。原图、对话和识别接口均由后端验证归属，账号不能读取其他账号的记录。详细说明见 [AUTH_ACCOUNTS.md](AUTH_ACCOUNTS.md)。

未登录时保留原有访客模式。登录或注册可选择“关联当前浏览器的访客历史”，一次性转移问答及识别记录；关联后原访客令牌不能再读取这些数据。清除站点数据前尚未关联的访客记录无法自动找回；已关联账号的记录可通过账号登录访问。

## 启动、停止与首次安装

已完成本机配置后，`start-platform.ps1` 自动启动项目独立 MySQL。停止网页执行 `stop-platform.ps1`，数据库继续运行；需要停止数据库时执行 `stop-mysql.ps1`，它通过经数据目录校验的本机管理连接安全关闭，数据保留。

```powershell
.\start-platform.ps1
.\stop-platform.ps1
.\stop-mysql.ps1
# 也可以单独启动数据库
.\start-mysql.ps1
```

新电脑先安装 MySQL 8.4 及项目 Python/前端依赖，再指定已安装的服务器程序建立独立实例：

```powershell
& .\TCMP-300\.venv-api\Scripts\python.exe .\TCMP-300\tools\local_mysql.py setup --mysqld '你的MySQL安装目录\bin\mysqld.exe' --port 3307
```

初始化生成随机数据库管理、应用及网页登录管理员密码，仅写入本地忽略文件；同时初始化认证和文章维护表。升级已有项目实例：先 `start-mysql.ps1`，再运行 `TCMP-300/tools/setup_auth.py`，已有管理员密码保持不变。已有其他 MySQL 实例时，也可在后端 `.env` 配置 `MYSQL_HOST`、`MYSQL_PORT`、`MYSQL_DATABASE`、`MYSQL_USER`、`MYSQL_PASSWORD`，设置 `MYSQL_ENABLED=true`、`MYSQL_MANAGED_LOCAL=false`；由具有建表权限的连接调用历史、内容、认证及文章维护模块的初始化函数，并配置独立 CSRF 密钥，再用受限账号运行 API。本机初始化工具不操作外部实例。

## 接口与验证

已登录历史接口使用 HttpOnly 会话 cookie；写入时附带 CSRF 校验头。访客使用 `X-History-Token` 请求头，由前端自动添加；不包含 DeepSeek 密钥。

- `GET/POST /api/v1/history/conversations`：分页读取或创建对话。
- `POST /api/v1/history/import`：导入旧浏览器记录。
- `GET /api/v1/history/recognitions`：搜索、分页读取识别记录。
- `GET /api/v1/history/recognitions/{id}/image`：读取本人记录的原图。
- 原问答和识别接口成功后返回 `saved=true`，并返回对话或识别记录 ID。
- `/api/v1/health` 的 `database.status` 表示数据库是否就绪。
- `GET /api/v1/articles` 和 `GET /api/v1/articles/{id}`：公开文章列表与正文，支持关键词和分类查询；封面使用 `GET /api/v1/articles/{id}/cover`。
- 原 `/api/v1/herbs` 系列接口结构保持兼容，读取 MySQL 图鉴。
- 健康检查的 `content` 字段显示 MySQL 图鉴和已发布文章数量。

```powershell
# 用独立临时测试库验证真实 MySQL；结束后只删除本次生成的测试库。
Push-Location .\TCMP-300
.\.venv-api\Scripts\python.exe -m unittest test_history_mysql -v
.\.venv-api\Scripts\python.exe -m unittest test_content_mysql test_mysql_connection -v
.\.venv-api\Scripts\python.exe -m unittest test_auth_admin_mysql -v
Pop-Location
```

对话记录、图片和数据库不随源码仓库同步。长期使用时需要分别备份 MySQL 数据和上传图片；只克隆 Git 仓库不能恢复本机历史记录。

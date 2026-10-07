# Codex 开发任务：中草药智能识别与知识平台（仅前端）

你现在需要完成一个课程项目的 **React 前端**。这是“AI 全栈开发”课程的实验 4，后端后续统一使用 **FastAPI**，但本任务 **只实现前端**。请把前端做到可运行、可演示、可继续接后端，而不是只搭静态页面。

我会同时提供 6 张已经确定的 UI 展示图，请把这些图片作为最高优先级视觉参考：

1. 首页
2. 草药图鉴
3. 数据看板
4. 本草科普
5. 关于项目
6. 登录页

请先完整查看这些参考图，再开始编码。页面整体风格、版式、色彩、卡片比例、留白、视觉层级、顶部导航、背景氛围都应尽量贴近参考图。不要擅自改成常见的 SaaS / 深色后台 / 蓝紫科技风。

---

## 一、项目背景

项目名称建议使用：

**中草药智能识别与知识平台**

本项目围绕 300 类中草药基源植物构建 AI 应用。已有数据包括：

- 约 300 类中草药/药用植物类别；
- `train / val / test` 图像数据集，图片为植物生长阶段图像，而非加工后的中药材照片；
- 一份结构化 Excel 草药知识数据，包括草药名称、类别、药性、性味、归经、功效、相关症状、药用部位等信息；
- 模型训练与优化由其他成员负责，已完成到实验 3；
- 实验 4 负责 React 前端 + FastAPI 后端集成；
- 当前任务只实现前端，并为后端 API 预留接口；
- 实验 5 后续会接入大模型 Agent，因此前端中的 AI 问答区域也需要提前保留完整结构。

项目定位：

> 基于图像识别、结构化中草药知识库和 AI 问答能力的中草药植物智能识别与知识服务平台。

前端主要实现：
- 中草药图片上传与识别；
- Top-K 识别结果展示；
- 草药知识详情；
- 草药图鉴与筛选；
- 草药搜索；
- 最近识别 / 最近浏览；
- 数据可视化；
- 本草科普内容展示；
- AI 问答界面；
- 项目介绍；
- 登录界面。

注意：项目用于教学、植物识别和传统中药知识科普，不设计在线诊断、处方或剂量建议功能。界面中如涉及医疗内容，请使用“知识科普”“传统应用”等中性表达。

---

## 二、技术栈要求

必须使用：

- React
- TypeScript
- Vite
- React Router DOM
- FastAPI 作为未来后端，但本任务不写 Python 后端

推荐使用：

- Axios：统一 API 请求
- ECharts：数据看板图表
- Tailwind CSS：快速还原设计稿
- Lucide React：通用线性图标
- Zustand（可选）：只在确实需要全局状态时使用

禁止：
- 不要用 Next.js
- 不要把所有代码写进一个 `App.tsx`
- 不要把后端逻辑硬编码到页面组件
- 不要把真实业务请求散落在各页面中
- 不要为了“视觉炫技”加入与设计图不一致的大面积玻璃拟态、霓虹、蓝紫渐变

---

## 三、项目目标

请直接创建一个完整、可运行的前端工程。

要求：

1. `npm install`
2. `npm run dev`

即可启动。

同时保证：

- 代码结构清晰；
- 页面路由完整；
- 组件可复用；
- 使用 TypeScript 类型；
- 所有业务接口统一从 `src/api` 调用；
- 在没有后端时，默认使用本地 mock 数据；
- 后续 FastAPI 上线后，只需修改环境变量和 API 实现，不需要重写页面；
- 桌面端优先还原参考图，同时保证平板和手机基本可用；
- 页面不要只做“截图式”静态 HTML，要有真实交互状态。

---

# 四、全局视觉规范

所有页面必须保持同一套视觉语言。

## 1. 风格

关键词：

- 中式本草
- 古典但不陈旧
- 自然植物感
- 淡雅高级
- 学术科普
- 中国水墨
- 现代 Web UI

使用：

- 淡米白 / 宣纸感背景
- 浅绿色、墨绿色作为主色
- 少量朱砂红印章作为点缀
- 淡墨山水纹理
- 竹叶、药草、植物线稿作为装饰
- 浅米白纸张感卡片
- 细线边框
- 柔和阴影
- 少量古籍、药臼、植物画等视觉元素
- 卡片圆角，但不要过度“卡通”

避免：

- 大面积高饱和绿色
- 蓝紫科技渐变
- 赛博朋克
- 深色后台系统
- 过度玻璃拟态
- 过度国潮金色
- 太多复杂纹样影响信息阅读

## 2. 主色建议

可以在 CSS 变量中定义：

```css
--color-primary: #1f7a58;
--color-primary-dark: #145b42;
--color-primary-light: #dcefe6;
--color-ink: #173b32;
--color-text: #24332e;
--color-muted: #708078;
--color-paper: #f7f4ea;
--color-card: rgba(255, 253, 247, 0.94);
--color-border: #d8dfd6;
--color-seal: #b54132;
```

允许根据参考图微调。

## 3. 字体

标题可以选择较有书卷感的中文字体回退栈，但不能依赖用户本地一定存在的商业字体。

正文优先使用：

```css
font-family:
  "Noto Sans SC",
  "PingFang SC",
  "Microsoft YaHei",
  sans-serif;
```

书法风标题可以使用：

```css
font-family:
  "STKaiti",
  "KaiTi",
  "Noto Serif SC",
  serif;
```

不要让正文大段使用楷体。

---

# 五、公共顶部导航栏

所有主页面保持统一 Header。

导航固定为：

- 首页
- 草药图鉴
- 数据看板
- 本草科普
- 关于项目

右侧依次为：

1. 搜索框
2. 用户图标 / 用户中心入口
3. 登录按钮

搜索框位置必须在“关于项目”和用户/登录区域之间。

搜索 placeholder：

**搜索草药 / 功效 / 别名**

当前页面对应导航项显示绿色激活状态和底部短横线。

建议路由：

```txt
/
 /herbs
 /dashboard
 /knowledge
 /about
 /login
 /herbs/:id
```

搜索行为：
- 输入关键词后回车；
- 跳转 `/herbs?q=关键词`；
- 草药图鉴页读取 query 参数并筛选；
- 可以加搜索建议下拉，但不是必须。

---

# 六、首页 `/`

请严格参考“首页展示图”。

首页首屏需要包括：

## 1. Hero 区

标题：

**看图识本草，智能问药理**

副标题围绕：

- AI 中草药识别
- 知识问答
- 科普平台
- 图像识别 + 大语言模型

右侧保持草药、植物、药臼、古籍等自然古典画面氛围。

Hero 下方有 4 个能力入口：
- 拍照识别
- 图鉴查询
- AI 问答
- 数据可视化

## 2. 草药识别区

左侧：
- 图片拖拽上传区域；
- “选择图片”按钮；
- 示例图片；
- 支持 JPG / PNG / WEBP；
- 上传后显示本地预览；
- 未接后端时用 mock 返回结果；
- 页面中要有 loading / success / error 状态。

后端未来接口：
`POST /api/v1/predict`

## 3. 识别结果区

展示：
- 草药图片
- 中文名
- 拉丁名
- 置信度
- 标签
- 简介
- Top 3 预测结果

识别结果右边或其后方，按照已确认首页展示图加入：

### 最近浏览

显示 3~5 条：
- 缩略图
- 草药名称
- 拉丁名
- 点击进入详情页

数据先用 mock。

## 4. 草药知识

显示当前识别草药的结构化属性：
- 别名
- 性味
- 归经
- 功效
- 主治/传统应用
- 注意事项

提供：
**查看完整资料 →**
跳转 `/herbs/:id`

## 5. AI 中医药助手

这里只做前端聊天 UI：
- 对话气泡
- 输入框
- 发送按钮
- 推荐问题 Chips
- 支持带上当前识别草药作为上下文
- mock AI 回复
- 为实验 5 Agent 留接口

未来接口：
`POST /api/v1/chat`

## 6. 常见中草药推荐

卡片如：
- 黄芪
- 甘草
- 金银花
- 丹参

每张卡片都可以点击进入：
`/herbs/:id`

## 7. 分类浏览

在首页下半部分增加分类浏览模块。

支持：
- 按功效
- 按药性
- 按药用部位
- 按科属
- 按首字母

点击后进入草药图鉴页并携带筛选 query。

## 8. 草药背景介绍 / 本草故事

必须放在首页继续向下滚动后的区域。

这是增强视觉吸引力的重要模块，需要比普通卡片更有“图文专题”感。

内容可以包括：
- 草药背景
- 本草故事
- 古代医药文化
- 药师/医者救治与采药的国风插画
- 古籍片段视觉
- 草药植物大图
- 中医药文化时间线

设计目标：
- 用户下滑后有“眼前一亮”的专题视觉；
- 图文交错；
- 不要全是等宽小卡片；
- 可使用大图横幅、左右分栏、长卷式布局；
- 点击进入本草科普页对应文章。

---

# 七、草药图鉴 `/herbs`

严格参考“草药图鉴展示图”。

## 顶部

页面标题：
**草药图鉴**

副标题：
**探索常见中草药的植物形态、性味归经与本草知识**

背景使用：
- 淡墨山水
- 浅米白宣纸纹理
- 竹叶 / 植物线稿
- 少量印章
- 不再照搬首页 Hero 的同一张场景图

已确认风格：
- 淡墨色背景纹理
- 浅米白纸张感卡片
- 绿色点缀
- 细线边框
- 少量印章元素

## 分类快捷入口

- 按功效分类
- 按药性分类
- 按药用部位
- 按科属分类
- 按首字母浏览

## 左侧筛选栏

至少包括：

### 功效
- 清热解毒
- 补气养血
- 活血化瘀
- 止咳平喘

### 药性
- 寒
- 热
- 温
- 凉
- 平

### 药用部位
- 根
- 茎
- 叶
- 花
- 果实
- 种子

### 排序
- 热门优先
- 名称排序
- 最近浏览

提供：
- 重置筛选

## 主内容区

顶部：
- “共收录 300 种中草药”
- 推荐排序
- 最新收录
- 网格/列表切换

草药卡片：
- 图片
- 中文名
- 拉丁名
- 属性标签
- 一句话简介
- 查看详情

所有卡片可点击 `/herbs/:id`。

右侧：
- 热门草药排行
- 本草文化小专题

## 草药详情页 `/herbs/:id`

虽然没有单独参考图，但必须实现。

延续同一视觉体系。

建议内容：
- 大图
- 中文名 / 拉丁名 / 别名
- 科属
- 植物形态
- 药用部位
- 性味
- 归经
- 功效
- 传统应用
- 注意事项
- 背景故事
- 参考图片
- 相似草药
- “向 AI 提问”按钮
- 返回图鉴

---

# 八、数据看板 `/dashboard`

严格参考“数据看板展示图”。

顶部 Hero 标题：
**数据看板**

描述：
可视化展示中草药数据资源、图像数据集统计与模型识别性能。

上方统计卡片：
- 草药类别：300
- 图像总量
- 模型准确率
- 今日识别次数
- 问答交互次数

数据可以先 mock，但统一放在 mock 数据文件中。

ECharts 至少实现：

1. 草药功效分类统计 —— 柱状图
2. 草药性味分布 —— 环形图
3. 图像数据集划分 —— 环形图
4. 模型训练过程 —— Accuracy / Loss 折线图
5. 近期识别趋势 —— 折线或面积图

另外显示：
- 模型 Accuracy
- Precision
- Recall
- F1
- 热门草药识别 TOP 5
- 数据资源概览

图表要适配容器 resize。

---

# 九、本草科普 `/knowledge`

严格参考“本草科普展示图”。

顶部：
- 标题：本草科普
- 大幅中式药文化场景
- 医者、药草、古籍、药房等视觉元素
- 保持高级、克制，不要做卡通国风

分类入口：
- 本草故事
- 草药背景
- 节气养生
- 药食同源
- 名医典故
- 安全常识

主推荐：
**今日推荐**
大图 + 本草故事图文。

文章区：
- 科普文章卡片
- 图片
- 标签
- 标题
- 摘要
- 阅读全文

右栏：
- 热门阅读
- 科普专题

页面下方继续可滚动，可加入：
- 四季本草 / 春夏秋冬
- 中医药文化长卷
- 古籍与植物插画

文章内容可以 mock，但结构要适合未来 API 替换。

---

# 十、关于项目 `/about`

严格参考“关于项目展示图”。

顶部：
- 标题：关于项目
- 描述这是 AI 全栈开发课程项目
- 展示“传统本草 + 数字技术 + AI”的视觉融合

模块包括：

## 项目背景
说明：
- 300 种中草药数据
- 图像识别
- 草药知识服务
- 中医药数字化科普

## 项目目标
四项：
- 中草药图像识别
- 知识查询与学习
- 数据可视化
- 智能问答与交互

## 实验路线
按课程实验 1~5 展示：

1. 实验一：数据采集与预处理
2. 实验二：模型训练
3. 实验三：算法优化
4. 实验四：前后端开发
5. 实验五：大模型 Agent 部署

## 技术栈
展示：
- React
- FastAPI
- PyTorch
- MySQL / SQLite
- ECharts
- LLM / Agent

本任务前端中：
React、ECharts 为实际使用；
其余说明为整个项目技术栈，不需要在前端实现后端代码。

## 系统架构
绘制前端式架构图：
- Web 用户端
- React
- FastAPI
- 图像识别模型
- 草药知识库
- LLM Agent
- 数据资源

## 数据与成果
如：
- 300 类
- 图像数量
- 模型准确率
- 图像识别 / 知识检索 / AI 问答

## 团队分工
使用 mock 成员，不要写真实姓名。
可以写：
- 数据处理
- 模型训练
- 前端开发
- 后端开发
- 文档汇报

---

# 十一、登录页 `/login`

严格参考“登录页展示图”。

顶部仍保留统一 Header。

主体采用左右布局：

左侧：
- 中式水墨山水
- 竹叶
- 药草
- 古籍
- 药臼
- 宣纸
- 本草文化视觉

右侧：
- 浅米白登录卡片
- Logo
- 平台名称
- 账号登录 / 验证码登录 Tab

账号登录：
- 账号 / 邮箱
- 密码
- 显示密码
- 记住我
- 忘记密码
- 登录按钮

可以保留：
- 微信登录
- QQ 登录
- GitHub 登录
- 立即注册

但都只做前端交互，不连接真实第三方 OAuth。

未来接口：
`POST /api/v1/auth/login`

登录后可 mock 保存 token，并让 Header 显示用户头像/用户名。

---

# 十二、API 预留

在：

```txt
src/api/
```

集中实现。

建议文件：

```txt
src/api/
  client.ts
  herb.ts
  recognition.ts
  dashboard.ts
  knowledge.ts
  chat.ts
  auth.ts
```

Axios baseURL：

```ts
import.meta.env.VITE_API_BASE_URL
```

默认：

```env
VITE_API_BASE_URL=http://localhost:8000
VITE_USE_MOCK=true
```

请实现 mock / real API 切换。

---

## 1. 图片识别

```http
POST /api/v1/predict
Content-Type: multipart/form-data
```

field:
`file`

返回示例：

```json
{
  "prediction": {
    "herb_id": "h001",
    "name": "金银花",
    "latin_name": "Lonicera japonica Thunb.",
    "confidence": 0.928,
    "image_url": "/static/herbs/jinyinhua.jpg"
  },
  "top_k": [
    {
      "herb_id": "h001",
      "name": "金银花",
      "confidence": 0.928
    },
    {
      "herb_id": "h078",
      "name": "忍冬藤",
      "confidence": 0.041
    },
    {
      "herb_id": "h109",
      "name": "山银花",
      "confidence": 0.023
    }
  ]
}
```

---

## 2. 草药列表

```http
GET /api/v1/herbs
```

参数：

```txt
q
effect
property
part
family
letter
sort
page
page_size
```

返回：

```json
{
  "total": 300,
  "items": []
}
```

---

## 3. 草药详情

```http
GET /api/v1/herbs/{id}
```

建议类型包含：

```ts
interface HerbDetail {
  id: string
  name: string
  latinName: string
  aliases: string[]
  family?: string
  genus?: string
  medicinalPart?: string[]
  property?: string
  flavor?: string[]
  meridians?: string[]
  effects?: string[]
  traditionalUses?: string[]
  morphology?: string
  habitat?: string
  background?: string
  precautions?: string[]
  imageUrls: string[]
}
```

---

## 4. 最近浏览

```http
GET /api/v1/history?limit=5
```

当前可使用 localStorage 模拟。

建议：
用户打开 `/herbs/:id` 时写入 localStorage。

---

## 5. 数据看板

```http
GET /api/v1/dashboard/summary
GET /api/v1/dashboard/charts
```

---

## 6. 科普文章

```http
GET /api/v1/articles
GET /api/v1/articles/{id}
```

---

## 7. AI 问答

```http
POST /api/v1/chat
```

请求：

```json
{
  "message": "金银花有哪些传统用途？",
  "herb_id": "h001",
  "session_id": "demo-session"
}
```

返回：

```json
{
  "answer": "……",
  "references": []
}
```

---

## 8. 登录

```http
POST /api/v1/auth/login
```

---

# 十三、推荐目录结构

请至少做到以下粒度：

```txt
src/
├─ api/
│  ├─ client.ts
│  ├─ auth.ts
│  ├─ chat.ts
│  ├─ dashboard.ts
│  ├─ herb.ts
│  ├─ knowledge.ts
│  └─ recognition.ts
│
├─ assets/
│  ├─ images/
│  ├─ textures/
│  └─ icons/
│
├─ components/
│  ├─ common/
│  │  ├─ Header.tsx
│  │  ├─ Footer.tsx
│  │  ├─ PageHero.tsx
│  │  ├─ SearchBar.tsx
│  │  └─ SectionTitle.tsx
│  ├─ herb/
│  │  ├─ HerbCard.tsx
│  │  ├─ HerbFilters.tsx
│  │  └─ RecentViewed.tsx
│  ├─ recognition/
│  │  ├─ ImageUploader.tsx
│  │  ├─ RecognitionResult.tsx
│  │  └─ PredictionTopK.tsx
│  └─ dashboard/
│     └─ ...
│
├─ data/
│  ├─ mockHerbs.ts
│  ├─ mockDashboard.ts
│  ├─ mockArticles.ts
│  └─ mockRecognition.ts
│
├─ layouts/
│  └─ MainLayout.tsx
│
├─ pages/
│  ├─ HomePage.tsx
│  ├─ HerbGalleryPage.tsx
│  ├─ HerbDetailPage.tsx
│  ├─ DashboardPage.tsx
│  ├─ KnowledgePage.tsx
│  ├─ AboutPage.tsx
│  └─ LoginPage.tsx
│
├─ types/
│  ├─ herb.ts
│  ├─ recognition.ts
│  ├─ dashboard.ts
│  └─ article.ts
│
├─ hooks/
├─ utils/
├─ styles/
├─ App.tsx
└─ main.tsx
```

---

# 十四、Mock 数据要求

在后端未完成时，所有页面都必须能完整演示。

至少准备 12~20 条示例草药，例如：

- 金银花
- 黄芪
- 甘草
- 丹参
- 菊花
- 连翘
- 当归
- 薄荷
- 枸杞
- 人参
- 板蓝根
- 蒲公英

每条至少包含：
- id
- name
- latinName
- aliases
- property
- flavor
- meridians
- effects
- medicinalPart
- description
- image

可使用项目本地占位图或我提供的参考素材。
禁止依赖经常失效的随机外链图片作为核心展示。

---

# 十五、交互要求

必须真正实现：

- React Router 页面跳转
- 导航激活状态
- 草药卡片点击详情
- 全局搜索
- 草药筛选
- 筛选重置
- 排序切换
- 网格/列表切换
- 图片上传预览
- 模拟识别 loading
- 模拟识别结果
- Top-K 结果
- 最近浏览 localStorage
- AI 聊天输入、发送、mock 回复
- 登录表单校验
- 登录态 mock
- 图表响应式
- 空状态
- 错误状态
- loading skeleton 或 loading 状态

---

# 十六、响应式

参考图以桌面宽屏为主，请优先精准完成：

- 1440px
- 1600px
- 1920px

同时保证：
- 1024px 平板可用；
- 768px 以下导航可折叠；
- 卡片网格自动变列；
- 图表不溢出；
- 登录页移动端改为单列；
- 左右侧栏在窄屏合理下沉。

---

# 十七、质量要求

代码要求：

- TypeScript 不滥用 `any`
- 避免超大组件
- 重复 UI 必须组件化
- 列表必须稳定 key
- 图片写 alt
- 表单有 label 或 aria-label
- 路由懒加载可选
- ESLint 无明显错误
- 无控制台大量 warning
- 不要保留大量无用模板代码
- 不要把所有页面样式堆到一个超大 CSS 文件

---

# 十八、完成标准

最终请完成：

1. 一个可直接运行的 React 前端；
2. 7 个路由页面：
   - 首页
   - 草药图鉴
   - 草药详情
   - 数据看板
   - 本草科普
   - 关于项目
   - 登录
3. 视觉尽量还原我提供的 6 张参考图；
4. 首页包含后续滚动区域：
   - 分类浏览
   - 本草故事 / 草药背景
5. 草药卡片全部可进入详情；
6. 最近浏览功能可用；
7. 搜索框可用；
8. 数据看板使用 ECharts；
9. API 层预留完善；
10. 默认 mock 模式可独立演示；
11. 提供 `.env.example`；
12. 更新项目根目录 README.md；
13. 运行并自测，修复明显布局和 TypeScript 错误。

---

# 十九、开发执行方式

请不要只给我代码片段或“实现思路”。

请直接在当前项目目录中：

1. 检查已有文件；
2. 初始化/完善 React + TypeScript + Vite 项目；
3. 安装需要的依赖；
4. 创建目录与组件；
5. 完成页面；
6. 根据参考图细调样式；
7. 运行构建；
8. 修复报错；
9. 确保 `npm run build` 通过；
10. 最后总结你创建和修改了哪些文件、怎么启动、哪些 API 已预留。

如果参考图和文字需求有冲突，以我本提示词中的明确文字需求为准；若没有冲突，则视觉优先参考图片。

请从阅读参考图和现有项目结构开始，直接完成整个前端。

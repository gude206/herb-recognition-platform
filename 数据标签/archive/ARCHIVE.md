# 历史页面归档

`removed-pages/` 保存已退出当前路由的「数据看板」「关于项目」源码、专属组件、演示数据、接口、类型、样式、装饰图片和原始页面参考图。目录结构保留原路径；源码没有参与当前 TypeScript 编译或 Vite 打包。

`removed-pages/src/styles/pages-legacy.css` 是从共享 `pages.css` 提取的旧页面区块；归档的 `responsive.css`、`tablet.css` 是相应历史响应式规则。图鉴仍使用 `src/assets/decor/dashboard-landscape.svg`，该共享图片保留在运行目录。

如需恢复旧页面，请将归档文件复制回对应路径，合并历史样式，恢复 ECharts 依赖和路由后重新验证。历史页面中的统计数字为课程演示数据。

`generated-config/` 保存原来生成在项目根目录的 Vite JavaScript 配置、声明和 TypeScript 构建缓存，供追溯。当前仅维护 `vite.config.ts`，所有 npm 命令显式指定它；新的 TypeScript 输出和构建缓存位于 `.build/`，不要将旧生成配置复制回根目录。

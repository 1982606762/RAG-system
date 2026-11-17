# 第一版第 1 阶段：原文定位

实现日期：2026-11-17。对应 [RAG_V1.md](RAG_V1.md) 的第 1 阶段。本阶段不包含向量生成、语义搜索或 AI 问答。

## 用户可见的变化

- 从搜索结果或片段点击「查看来源」，TXT/Markdown 会打开原件，滚动并高亮对应原段落，显示行号。
- 本地解析的 Markdown 定位范围包含原始标题标记、表格分隔线与代码围栏；原件仍按安全纯文本显示。
- PDF 打开来源页，以页面图片显示，有可靠区域时覆盖高亮框；可以前后翻页。手动翻页会清除先前来源框。
- 本地 OCR 的段落框按识别图片尺寸归一化，供扫描 PDF 和单张图片定位。
- 旧资料没有新字段时，TXT/Markdown 保留提取内容块定位，PDF 保留页码定位，并说明精度。
- Google 文本解析仅对唯一且完全一致的原文匹配保存字符范围。重复文本和改写内容不会猜测位置。
  Google PDF 目前没有可靠区域映射，使用逐页发送时保存的物理页码打开页面。
- 页面图片生成失败时，回退到浏览器 PDF 阅读器；原件下载仍可使用。

## 数据和接口约定

沿用 `blocks.data` JSONB，新增可空的 `Block.location`，不需要数据库迁移。已有 `chunk.sources.start/end` 仍表示解析后的 `block.text` 区间，不能当作原件偏移。

| 原件类型 | `location` | 参照对象 |
| --- | --- | --- |
| TXT/Markdown | `{type: "text", start, end, start_line, end_line}` | 原件按 UTF-8-sig 解码后的 Unicode code points；去掉 BOM，保留 CRLF；字符区间为 `[start, end)`，行号从 1 开始。 |
| PDF/图片 | `{type: "page", page, bbox?}` | 从 1 开始的物理页码；`bbox` 为左上角原点的 `[x0, y0, x1, y1]`，归一化到实际展示区域的 0–1。 |
| 无可靠映射 | `null` 或字段缺失 | 阅读器使用内容块或已知页码回退，不推断坐标。 |

本地 PDF 从原始 crop/media box 的相交范围出发，处理显示旋转，再将 pdfplumber 坐标归一化。
本地新解析版本为 `local-blocks-v2`，Google 为 `google-layout-v2`；分块版本不变。
原有成功资料不会自动重解析，重复上传也仍然打开原记录，因此不会为了补定位再次调用 Google。

新增 `GET /api/documents/{uuid}/pages/{page}/preview`：沿用 owner 认证；返回 PNG，设置 `Cache-Control: no-store` 和 `X-Content-Type-Options: nosniff`。
页码限定 1–50，并核对实际页面是否存在。预览最长边约 1600 像素，30 秒超时。
PDFium 的调用放在单独子进程中，避免与上传解析线程并发使用同一个 PDFium 进程。沿用现有依赖。

## 本地验证

- 后端 44 项测试：43 项通过；PGlite 无法代表原生 PostgreSQL 多连接锁语义，1 项已有并发测试明确跳过。
  已验证真实 Tesseract OCR、Google 文本解析适配（模拟 provider 响应）、文本范围持久化、PDF 上传/解析/分页预览往返。
- 新增几何验证：合成带非对称裁剪框的 PDF，分别旋转 0°、90°、180°、270°，检查渲染文字像素是否落在来源区域。
- 前端 16 项组件测试通过；TypeScript 检查与 Vite 构建通过。
  覆盖 emoji/CRLF、原件安全渲染、搜索与片段定位、旧资料回退、PDF 高亮和手动翻页清除高亮。
- Chromium 完整链路通过：登录、上传、去重、分块、关键词搜索到原件、高亮 PDF、失败重试、下载、安全文本渲染、390px 手机布局。
  本次仅使用本机临时内存数据库和合成文件。Google 真实云端调用及生产部署未执行。

完整回归沿用 README 命令和 `frontend/tests/mvp_smoke.py`。原生 PostgreSQL 并发验证仍由配置独立测试数据库的环境执行。

## 限制与后续

- 定位精度为内容块；表格当前高亮整块或 OCR 段落，没有逐行/逐单元格映射。
- 分页图片不提供浏览器 PDF 的文字选择；仍可下载原件使用常规 PDF 阅读器。
- 不维护历史解析版本。未来问答的持久化引用需要绑定解析版本，不能只保存会变化的块索引。
- 下一阶段按设计接入 Vertex AI embedding 与 pgvector，保持文档可阅读状态和向量化状态分离。

## 本次文件改动

以下只列本阶段的增量，不代表当前工作区所有未提交改动。

| 文件 | 本阶段操作与用途 |
| --- | --- |
| `app/documents/models.py` | 修改：为内容块增加独立原件位置。 |
| `app/documents/parsing.py` | 修改：保存文本原始范围、PDF 显示坐标及 OCR 区域，提升本地解析版本。 |
| `app/documents/locations.py` | 新增：PDF 旋转/裁剪坐标转换及唯一原文匹配。 |
| `app/documents/google_ocr.py` | 修改：为可确定的 Google 文本结果关联原件范围。 |
| `app/documents/service.py` | 修改：记录新 Google 解析版本。 |
| `app/documents/preview.py` | 新增：隔离且限时的 PDF 页面渲染。 |
| `app/api/documents.py` | 修改：增加受保护的页面预览接口。 |
| `app/tests/test_locations.py` | 新增：原件位置、真实几何和接口边界回归。 |
| `app/tests/test_ingestion_integration.py` | 修改：验证位置持久化及 PDF 预览往返。 |
| `frontend/src/api.ts` | 修改：增加来源位置类型和分页预览请求。 |
| `frontend/src/components/DocumentReader.tsx` | 修改：搜索/片段跳转原件、翻页与回退。 |
| `frontend/src/components/OriginalText.tsx` | 新增：按 code points 高亮原始文本。 |
| `frontend/src/components/PagePreview.tsx` | 新增：加载页面图片和来源框，失败时回退。 |
| `frontend/src/i18n.ts` / `index.css` | 修改：定位说明、中英文文案与高亮样式。 |
| `frontend/tests/documents.test.tsx` | 修改：补充预览 API mock，保留已有行为回归。 |
| `frontend/tests/locations.test.tsx` | 新增：原件定位和 PDF 高亮交互测试。 |
| `frontend/tests/mvp_smoke.py` | 修改：验收真实搜索到原件及 PDF 来源高亮。 |
| `README.md` / `docs/RAG_V1.md` / `docs/MVP.md` | 修改：同步能力、阶段状态与历史边界。 |
| `docs/ORIGINAL_LOCATIONS.md` | 新增：本阶段实现、验证和限制。 |
| `docs/learning/ORIGINAL_SOURCE_MAPPING.md` | 新增：学习材料；未改动正式笔记目录。 |

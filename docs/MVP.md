# 文档 MVP：范围、验证与改动

## 已实现范围

本次确认的范围是上传、解析、分块和查看。没有加入搜索、embedding 或 AI 问答。

1. 登录后选择文件，上传请求串行完成保存、解析、内容块持久化、分块和片段持久化。
2. 使用 SHA-256 去重；同一内容重新上传会打开已有记录。
3. 失败保留原件和错误阶段，允许手动重试。处理成功前不将文档标记为 ready。
4. 文档列表提供分页；详情切换原件、提取内容和片段；片段可以定位回内容块或 PDF 页码。
5. 下载和预览通过带 Bearer token 的接口读取，原件目录不提供公开静态访问。

## 解析与分块约定

- PDF：pdfplumber 按页提取文字与网格表格，排除表格区域的重复正文。
- 扫描页/图片：Tesseract 本地 OCR，不发送给外部 AI。默认语言 `eng+dan+chi_sim`。
- 文本：UTF-8；Markdown 保留 ATX 标题、段落、围栏代码和简单管道表格。
- 内容块记录类型、文字、章节路径、页码和可用的 PDF 坐标。OCR 目前只定位到页。
- 片段来源保存块索引和块内字符区间，正文可由这些来源精确重建。
- 普通短段落按章节合并，长段落按句子切分；跨页不强制断开，跨章节不合并。
- 表格优先按行切分并重复第一行；第一行作为表头是 MVP 假设，无表头表格需要人工核对。
- 目标 1600、最大 2400、长段落重叠最多 200，单位均为 Unicode 字符，不是 tokens。
  没有句子边界时使用长度兜底，不强行插入不完整的重叠句子。

## 已知限制

- 复杂多栏 PDF、旋转文字、跨页表格、合并单元格、图表语义和手写体没有专门处理。
- PDF 标题以简单编号规则识别；不会完整还原所有字体层级。
- 有文字层的页面中，插图内容不单独 OCR；页面会提示可能遗漏图片中的信息。
- OCR 表格保留识别文本，不保证恢复行列关系。数字、低置信度文字及页面识别提示应与原件核对。
- 页眉页脚暂时保留，避免误删正文；目录没有特殊降权。
- TXT/Markdown 的来源定位到内容块，不提供原件行号；PDF 可以定位到物理页码。
- 数据库状态与文件系统无法组成一个原子事务。元数据写入失败时保留原件，可能留下未被记录的文件，
  不自动删除不明原件。磁盘故障仍需要备份恢复。
- 重启不续跑；下次读取列表/详情或开始处理时，持锁确认没有活跃入库后标记中断状态。
- 当前保留解析版本和分块参数，但不维护多个历史版本，也没有可点击的 AI 回答引用。
- 120 秒是解析软预算，页间检查；OCR 有单次子进程超时。nginx 等待超时不会自动取消服务端处理。
- 详情目前一次读取全部内容块和片段；大文件阅读性能后续可按页优化。

## 运行与验证

启动步骤见 [DEPLOY.md](../DEPLOY.md)。

### 后端基础测试

```bash
conda activate rag
pip install -r app/requirements.txt -r app/requirements-test.txt
PYTHONPATH=app python -m unittest discover -s app/tests -v
```

基础测试包含认证边界、真实 PDF/表格提取、中英分块、来源重建、大小限制和原生 OCR。
缺少 Tesseract 时原生 OCR 测试会明确跳过。

### 原生 PostgreSQL 集成测试

仅对专用测试数据库执行；测试初始化 MVP schema，写入合成资料，完成后删除自己创建的记录。

```bash
export RAG_TEST_PG_DSN='postgresql://postgres:test-password@localhost:5432/rag_mvp_test'
PYTHONPATH=app python -m unittest discover -s app/tests -v
```

涵盖完整上传/读取/下载、重复内容、失败保留、手动重试、片段事务回滚、中断恢复、并发锁和路径隔离。
测试可选使用 PGlite 做 SQL 验证，此时设置 `RAG_TEST_DB_FLAVOR=pglite`；会禁用测试连接的 prepared
statements，并跳过原生 advisory-lock 并发验证，不改变生产代码。

### 前端与浏览器

```bash
cd frontend
npm ci
npm test
npm run build
```

组件测试验证上传等待、重复文件、错误提示、来源跳转、安全文本渲染、PDF 页链接和英文控件。

真正的浏览器验收需要独立运行的应用与空的测试资料库，并会上传合成文件：

```bash
pip install playwright
python -m playwright install chromium
export RAG_E2E_PASSWORD='your-test-owner-password'
export RAG_E2E_BASE_URL='http://127.0.0.1:3000'
python frontend/tests/mvp_smoke.py
```

`.github/workflows/test.yml` 在临时 PostgreSQL 16 上执行后端、前端和浏览器测试。
本次本机已验证内容：后端单元/OCR 与 PGlite SQL 集成、前端组件测试和构建。
本机原生 PostgreSQL 受共享内存权限限制，Chromium 受 macOS 进程权限限制；
原生数据库并发与真实浏览器视觉验收尚待 CI 或正常开发环境运行。本次未推送或触发 CI。

## 本次文件改动

以下只列文档 MVP 的改动，之前的旧链路删除见 `CLEANUP.md`。

| 文件 | 操作 | 用途 |
| --- | --- | --- |
| `app/documents/__init__.py` | 新增 | 文档模块入口 |
| `app/documents/models.py` | 新增 | 内容块、片段和业务错误 |
| `app/documents/parsing.py` | 新增 | 文本、PDF、表格和 OCR 解析 |
| `app/documents/chunking.py` | 新增 | 按结构与字符预算分块，保存来源区间 |
| `app/documents/service.py` | 新增 | 原件保存、去重、串行处理与重试 |
| `app/db/documents.py` | 新增 | 文档读写、事务和入库锁 |
| `app/db/migrations/001_documents.sql` | 新增 | 独立 schema 的三个业务表 |
| `app/api/documents.py` | 新增 | 五类受保护的文档接口 |
| `app/main.py` | 修改 | 注册文档路由和稳定错误响应 |
| `app/core/config.py` | 修改 | 文件目录、大小、页数和 OCR 设置 |
| `app/cli.py` | 修改 | 显式初始化数据库命令 |
| `app/requirements.txt` | 修改 | 加入 multipart、pdfplumber、pytesseract |
| `app/requirements-test.txt` | 新增 | 测试用 httpx 与 reportlab |
| `app/Dockerfile` | 修改 | 安装本地 OCR 与语言包 |
| `app/tests/test_shell.py` | 修改 | 将新文档路由从已移除路由断言中移出 |
| `app/tests/test_documents.py` | 新增 | 解析、分块、OCR 和认证测试 |
| `app/tests/test_ingestion_integration.py` | 新增 | 数据库完整流程与异常测试 |
| `frontend/src/api.ts` | 修改 | 文档 API、类型、上传进度与超时 |
| `frontend/src/pages/WorkspacePage.tsx` | 修改 | 上传、分页列表、状态和重试 |
| `frontend/src/components/DocumentReader.tsx` | 新增 | 原件、提取内容、片段与来源查看 |
| `frontend/src/i18n.ts` | 修改 | 中英文文档界面文案 |
| `frontend/src/index.css` | 修改 | 文档与阅读布局、窄屏适配 |
| `frontend/nginx.conf` | 修改 | 上传大小与长请求超时 |
| `frontend/package.json` / `package-lock.json` | 修改 | 组件测试命令与开发依赖 |
| `frontend/vitest.config.ts` / `tests/setup.ts` | 新增 | 组件测试环境 |
| `frontend/tests/documents.test.tsx` | 新增 | 前端交互回归测试 |
| `frontend/tests/mvp_smoke.py` | 新增 | 浏览器完整链路验收脚本 |
| `.github/workflows/test.yml` | 新增 | 临时 PostgreSQL/OCR/浏览器 CI 验证 |
| `docker-compose.yml` | 修改 | 单独可写的新原件目录 |
| `.env.example` | 修改 | OCR 语言配置示例 |
| `README.md` / `DEPLOY.md` | 修改 | 当前能力和启动步骤 |
| `docs/REBUILD.md` | 修改 | 将已确认 MVP 与后续检索规划分开 |
| `docs/MVP.md` | 新增 | 本说明与验收边界 |

未修改真实 `.env`、旧原件或生产数据库，未提交、推送或部署。

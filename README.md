# 个人知识库

单人使用、PC 优先的资料管理项目。当前 MVP 已实现 **上传 → 保存原件 → 本地解析 → 分块 → 查看与定位来源**。
文件处理在当前请求内顺序执行，不使用 worker、队列或云端模型。

## 当前能力

- 单密码登录，所有文档接口及原件下载均校验 owner JWT。
- 上传 PDF、UTF-8 TXT/Markdown、PNG/JPEG/WebP；最大 20 MiB，PDF 最多 50 页。
- SHA-256 内容去重；原件单独保留，失败状态与原因持久化，可手动重试。
- PDF 文字层与网格表格提取；扫描页和图片使用 Tesseract OCR（中、英、丹麦语）。
- 解析内容块和检索片段分别保存，保留章节、页码、块内字符范围和处理版本。
- 按章节、段落和表格分块；目标 1600 字符，上限 2400，长段落句子重叠上限 200 字符。
- 前端资料列表、原件预览/下载、提取内容、片段与来源跳转；支持中英文界面和窄屏布局。

**尚未实现**：embedding、pgvector、搜索、AI 问答、会话、cardless 集成和自动重试。
`ready` 目前表示解析和分块完成，不表示已有检索索引。
财务资料管理属于 cardless，未来只读调用其 API。

## 启动

完整步骤见 [DEPLOY.md](DEPLOY.md)。已有安装必须合并配置，不能覆盖 `.env`。
配置认证后：

```bash
docker compose build
docker compose up -d postgres
docker compose run --rm app python cli.py init-db
docker compose up -d
```

打开 `http://localhost:8001`。`init-db` 是显式、可重复执行的初始化命令，
只创建 `knowledge_base_v1` schema 中的新表，不修改旧表或迁移旧数据。
新上传保存在 `files/mvp/`；旧 `files/` 原件保持只读挂载。

## 代码结构

```text
app/
  main.py                    # Route assembly and error responses
  api/documents.py           # Upload, list, detail, download, retry
  api/auth.py                # Single-owner login
  api/deps.py                # Shared owner authentication
  documents/models.py        # Parser blocks and chunks
  documents/parsing.py       # Text/PDF parsing and local OCR
  documents/chunking.py      # Structure-first character-based splitting
  documents/service.py       # Synchronous ingestion lifecycle
  db/documents.py            # Persistence, transactions, ingestion lock
  db/migrations/001_documents.sql
  core/config.py             # Authentication, storage and processing limits
  cli.py                     # Password, database health and init-db
  tests/                     # Unit and opt-in database integration tests
frontend/
  src/pages/WorkspacePage.tsx
  src/components/DocumentReader.tsx
  tests/documents.test.tsx    # Component interaction tests
  tests/mvp_smoke.py          # Browser smoke test for disposable deployments
```

## 验证

```bash
conda activate rag
pip install -r app/requirements.txt -r app/requirements-test.txt
PYTHONPATH=app python -m unittest discover -s app/tests -v
cd frontend
npm ci
npm test
npm run build
```

没有 `RAG_TEST_PG_DSN` 时跳过数据库集成测试；没有 Tesseract 时跳过原生 OCR 测试。
完整测试方式、已知限制和本次改动文件见 [docs/MVP.md](docs/MVP.md)。
后续规划见 [docs/REBUILD.md](docs/REBUILD.md)；旧版清理记录见 [docs/CLEANUP.md](docs/CLEANUP.md)。
历史 `CLAUDE.md` 中的 Chroma/财务提取架构已过时，以这里和实际代码为准。

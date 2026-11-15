# 运行文档 MVP

当前提供登录、文档上传、解析、分块、原件与结果查看。不包含搜索或 AI 问答。
Docker Compose 的前端与 API 共用 `http://localhost:8001`，生产 OCR 依赖已安装在后端镜像内。

## 新安装

```bash
cp .env.example .env
```

编辑 `.env`，设置随机的 `POSTGRES_PASSWORD` 和 `JWT_SECRET`。
可用 `openssl rand -hex 32` 生成 JWT 密钥。

```bash
docker compose build
docker compose run --rm --no-deps app python cli.py hash-password
```

将命令输出的整行 `OWNER_PASSWORD_HASH='...'` 写进 `.env`，保留单引号，
避免 bcrypt 哈希中的 `$` 被 Compose 插值。密码命令不会写入数据库。

```bash
docker compose up -d postgres
docker compose run --rm app python cli.py init-db
docker compose up -d
docker compose exec app python cli.py healthcheck
curl --fail http://localhost:8001/api/health
```

打开 `http://localhost:8001`，登录并上传一份测试文件。
`init-db` 创建 `knowledge_base_v1.documents/blocks/chunks`，可重复执行，不删除已有记录。
API 不自动执行 DDL；未初始化时，文档接口返回带 `schema_missing` 的 503。
`/api/health` 只验证数据库连通性，不替代 schema 或上传链路验收。

## 已有安装

不要覆盖 `.env`，保留原数据库密码，合并新认证设置与 `OCR_LANGUAGES`。
修改 `POSTGRES_PASSWORD` 不会更改已有卷中的数据库账户密码。
先备份原文件、PostgreSQL 和旧向量卷。

旧 `public` schema、`files/` 中原文件及旧卷不做自动迁移或删除。
旧原件继续通过 `/files` 只读挂载；新原件在 `files/mvp/`，单独可写挂载为 `/documents`。
新应用不会通过 API 暴露旧业务记录。将来迁移需要明确核对原件及所属关系。

如果从旧版本升级，在切换源码前停止新上传并等旧任务结束，然后停止旧服务：

```bash
docker compose stop celery_worker redis chroma
```

如果这些服务已在之前清理，跳过这一步。然后切换源码，按上面的 build、init-db、up 顺序启动。
不要执行 `docker compose down -v` 或卷清理命令。

## API

文档路由均需要 `Authorization: Bearer <token>`。

| 接口 | 用途 |
| --- | --- |
| `POST /api/auth/login` | 单密码换取 JWT |
| `GET /api/auth/me` | 校验主人会话 |
| `GET /api/health` | 数据库连通性，无认证 |
| `GET /api/documents?limit=30&offset=0` | 分页列表，最大每页 100 条 |
| `POST /api/documents` | multipart 的 `file` 字段；等待本次解析和分块完成 |
| `GET /api/documents/{id}` | 文档信息、内容块、片段及来源 |
| `GET /api/documents/{id}/original` | 带认证的原件下载 |
| `POST /api/documents/{id}/retry` | 手动重试失败文件 |

上传成功接收后返回 `{document, duplicate}`，包括处理失败但已保存原件的情况；前端必须检查 `document.status`。
重复内容返回原记录，不自动重试。参数错误、空文件、不支持类型、超限分别使用 4xx。
另有文件正在处理时返回 409 `busy`，不排队。

处理状态是 `processing / ready / failed`，阶段是 `saved / parsing / chunking / complete`。
页面请求超时或关闭不代表后端已经停止处理；重新打开列表并刷新状态。
在没有活跃入库锁时，读取列表/详情或开始新处理会将中断的 `processing` 标记为失败，等待手动重试。

旧 `/api/upload`、注册、任务、对话、模型选择与追踪接口不再使用。
修改密码不会撤销已签发 token；需要全员重新登录时轮换 `JWT_SECRET`。

## 本地开发

```bash
conda activate rag
pip install -r app/requirements.txt
```

扫描件/图片还需要 Tesseract 和 `eng/dan/chi_sim` 语言包。
例如 macOS 可使用 `brew install tesseract tesseract-lang`；不安装时普通文本 PDF、TXT/Markdown 仍可处理。
缺少 OCR 时扫描件会保存为失败记录，并显示明确提示。

通过运行环境设置 `JWT_SECRET`、`OWNER_PASSWORD_HASH` 和 `PG_DSN`
（也可使用 libpq 的 `PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD`）。
裸 Python 不自动加载根目录 `.env`。默认 `DOCUMENTS_DIR` 为项目 `files/mvp/`，可显式覆盖。

```bash
cd app
python cli.py init-db
uvicorn main:app --reload --port 8001
```

另一个终端：

```bash
cd frontend
npm ci
npm run dev
```

打开 `http://localhost:3000`，Vite 将 `/api` 代理至 `8001`。

## 限制与运维

- 文件最大 20 MiB，PDF 最大 50 页，提取文本最多 100 万字符。
- nginx 请求体上限 21 MiB（包含 multipart），上游等待 150 秒；前端处理请求等待 155 秒。
- 解析有 120 秒软预算，在页间及 OCR 前后检查；单次 OCR 最长 45 秒且不超过剩余预算。
  本地 PDF 解析器单页调用无法被这个软预算中途打断；异常复杂文件应拆分。
- PostgreSQL session advisory lock 保证同时仅处理一份文档，其他请求仍可读取资料。
  使用直接 PostgreSQL 连接；不适配 transaction-pooling 模式的连接池。
- 失败保留原件和已成功写入的解析块；片段写入是原子事务。无后台任务、自动重试或断点续跑。
- 备份必须包含 `pgdata` 与 `files/mvp/`。备份前暂停上传，保持文件和元数据一致；旧备份单独保留。
- 公网使用前配置 HTTPS；仓库的 nginx 不终止 TLS。

GitHub Actions 部署仍为手动触发；首次部署 MVP 前须执行 `init-db`，常规更新不自动清理数据。
测试工作流使用临时 PostgreSQL 与合成资料，不访问生产环境。

```bash
docker compose logs -f app
docker compose ps
```

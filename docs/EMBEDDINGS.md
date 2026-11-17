# 第一版第 2 阶段：向量入库

实现日期：2026-11-17。已实现和测试 Vertex REST 适配、pgvector 持久化及恢复流程；真实云端调用尚待 Google 项目启用 API 和配置 IAM 后验收。当前仍只有关键词搜索，语义搜索属于下一阶段。

## 当前行为

- 新上传先完成解析和分块，提交 `document.status=ready`，再尝试向量化。向量化失败不会撤销解析，也不会影响原件阅读或关键词搜索。
- 文档详情和列表独立显示向量状态；详情提供「生成 / 继续向量化」，只读取已保存的 chunks，不调用 Document AI，也不要求重新上传。
- 默认模型为 `gemini-embedding-001`，每次请求一个输入，文档任务为 `RETRIEVAL_DOCUMENT`，请求 768 维，检查数值并进行 L2 归一化。
- `autoTruncate=false` 交由模型检查 token 上限；超限错误或返回的截断统计都触发细分，拒绝把字符数当成 token 数。当前适配的上限为 2048 tokens。
- 超限片段递归细分，保存子段在父 chunk 中的 Unicode 字符区间、实际输入的 SHA-256、正文和来源块区间。分段计划替换为原子事务；成功子段分别落库，下次继续跳过。
- 同一输入重复执行不产生重复向量；模型、区域、项目或输入策略改变会进入另一套 profile。当前状态只读取当前 profile。重新解析/分块删除旧 chunks 时，外键级联清除所有模型的旧向量。
- 仍是请求内串行处理，复用数据库 session advisory lock，无后台队列、自动重试或重启续跑。服务重启后把孤立的向量处理中状态标记为可继续的失败。

## Google 配置

沿用现有 ADC，不增加 Python SDK。需要启用 `aiplatform.googleapis.com`，并为该 ADC 身份授予 Vertex AI 调用权限（通常使用 `roles/aiplatform.user`）。Document AI API User 权限本身不等于 Vertex 调用权限。

```dotenv
# 可省略：未显式设置时使用 GOOGLE_CLOUD_PROJECT，再使用 Document AI 处理器的项目。
VERTEX_EMBEDDING_PROJECT=your-project-id
VERTEX_EMBEDDING_LOCATION=europe-west4
VERTEX_EMBEDDING_MODEL=gemini-embedding-001
```

没有可确定的项目时状态为 `disabled`，不发起云请求。项目已配置但 API 未启用时，文档仍为 ready，向量状态为 failed，错误为 `embedding_api_disabled`。启用后点击继续即可，无需重传。

本次预检中，生产项目 `724252786642` 返回 `SERVICE_DISABLED`，现有 ADC 也无启用服务的权限。用户选择稍后处理 Google 配置，因此没有将模拟向量当作真实云端成果，也没有修改 IAM 或凭据。

## CLI 与接口

在已加载运行环境的 `app` 目录中：

```bash
python cli.py check-embeddings
python cli.py embed-documents --limit 100
python cli.py embed-documents --document-id DOCUMENT_UUID
```

`check-embeddings` 向模型发送一段合成短文本检查认证、区域、维度和统计，不写业务数据。回填按创建时间读取已就绪资料，默认最多 100 份，每份 120 秒预算；退出码非零表示有未完成项目。重复执行会复用成功子段。

生产环境从活动发布的配置运行，保留 ADC 挂载和环境，例如在服务器项目根目录中：

```bash
docker compose -p rag-system -f .current-release/production.json exec app python cli.py check-embeddings
docker compose -p rag-system -f .current-release/production.json exec app python cli.py embed-documents
```

owner 接口：`POST /api/documents/{id}/embeddings`。返回带 `embedding` 字段的文档；模型请求失败时 HTTP 200 也可能对应 `embedding.status=failed`，因为原文仍然可用，应检查状态和错误。文档未 ready、已有处理在运行、未配置项目分别返回 409 / 409 / 503。

```json
{
  "embedding": {
    "status": "failed",
    "model": "projects/.../locations/europe-west4/publishers/google/models/gemini-embedding-001",
    "dimensions": 768,
    "completed_chunks": 1,
    "total_chunks": 3,
    "vector_count": 2,
    "error_code": "embedding_quota",
    "error_message": "向量服务暂时达到调用额度，请稍后继续。"
  }
}
```

一个 chunk 可能拆出多个向量，因此向量数量不等于已完成 chunk 数量。Web 单次向量化预算为 30 秒，超时保留进度；CLI 每份预算为 120 秒。模型侧没有自动重试，避免隐藏费用和长时间等待。

## 数据库与部署

`002_embeddings.sql` 安装 `vector` 扩展，新增 `embedding_runs` 与 `embedding_parts`。不会修改原件、blocks 或原有 chunk 正文。初始化按编号执行所有幂等迁移。

Compose 和 CI 使用 `pgvector/pgvector:0.8.7-pg16-trixie`。现有生产是 PostgreSQL 16 / Debian trixie，因此沿用 PG16 和同系统系列、原 `pgdata` 卷、连接配置和网络。部署先下载/构建镜像、验证凭据、停止写入、备份数据库和原件，再更换 PG16 容器并检查扩展可用性，最后执行迁移。

数据库启动失败时恢复旧 PG16 镜像；新 pgvector 数据库通过检查并完成迁移后，应用回滚保留该数据库镜像，避免扩展文件消失。不执行清卷或自动恢复旧备份覆盖新数据。

## 验证与边界

- 使用独立临时 PostgreSQL 16 + pgvector 测试数据库与模拟 provider 响应，验证成功入库、部分失败、子段复用、CLI 回填、模型隔离、重解析失效及真实 session lock 并发。
- 使用全新临时数据卷演练普通 PostgreSQL 16 到 pgvector 镜像的替换，检查旧记录仍在、扩展可安装且向量类型可用。
- 后端共 61 项测试、前端 22 项组件测试；另通过 TypeScript/Vite 构建。前端覆盖独立进度、继续请求、超时不确定性、刷新后保留请求错误、未配置状态及解析期间禁止生成。
- Chromium 基础链路覆盖上传、阅读、搜索和定位；额外用只存在于临时测试启动器的假 provider 验证「部分失败仍可读 → 继续后 3/3 就绪 → 重复检查不增加调用」，并检查 390px 手机布局。假 provider 不进入应用代码或生产镜像。
- Google 真实 embedding、实际权限及真实资料的向量效果待 API/IAM 配置后验证；本阶段没有语义查询或生成答案。
- 云端成功与数据库提交不能组成一个事务。若云端已计算但响应丢失/进程在落库前退出，重试可能再次调用并计费；已落库的检查点才可跳过。

## 主要改动

| 文件 | 用途 |
| --- | --- |
| `app/embeddings/provider.py` | REST、ADC、模型身份、维度/数值/截断检查和归一化。 |
| `app/embeddings/service.py` | 独立状态、持久化分段、来源映射、继续与回填。 |
| `app/db/embeddings.py` / `migrations/002_embeddings.sql` | 向量和检查点、状态汇总、外键失效。 |
| `app/db/documents.py` / `documents/service.py` | 多迁移、就绪后向量化、中断恢复与重解析失效。 |
| `app/api/documents.py` / `cli.py` / `core/config.py` | 主人接口、CLI 与独立项目/区域/模型配置。 |
| `frontend/src/components/EmbeddingPanel.tsx` | 向量状态、进度、错误和继续按钮。 |
| `frontend/src/components/DocumentReader.tsx` / `pages/WorkspacePage.tsx` | 阅读器、列表与状态刷新。 |
| `app/tests/test_embeddings*.py` / `frontend/tests/embeddings.test.tsx` | 故障、来源、生命周期与交互验证。 |
| `docker-compose.yml` / `.github/workflows/test.yml` / `scripts/` | PG16 pgvector 镜像、迁移、保留数据的发布及验收。 |

参考：[Google REST 参数与统计](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/model-reference/text-embeddings-api)、[Google 模型区域](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/locations)、[pgvector 安装](https://github.com/pgvector/pgvector#installation)。

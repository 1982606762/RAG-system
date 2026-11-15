# 本次精简的文件变更

原始文件、现有数据库、Docker 卷及本地 `.env` 未修改；未提交、推送或部署。

| 文件 | 操作 | 变更 |
| --- | --- | --- |
| `.env.example` | 修改 | 替换为单人访问密码哈希、JWT 和数据库配置示例。 |
| `.github/workflows/deploy.yml` | 修改 | 改为手动部署，健康检查仅检查保留的 PostgreSQL。 |
| `DEPLOY.md` | 修改 | 重写新骨架启动、旧数据保护和认证配置说明。 |
| `README_docker.md` | 修改 | 移除过时双数据库教程，转向当前运行文档。 |
| `app/Dockerfile` | 修改 | 保留 FastAPI 构建入口，移除旧存储架构注释。 |
| `app/api/auth.py` | 修改 | 移除注册和用户表访问，只保留主人密码登录及会话校验。 |
| `app/api/conversations.py` | 删除 | 删除旧多用户对话接口，等待新问答模型实现。 |
| `app/api/deps.py` | 修改 | 使用 require_owner 统一保护私有接口。 |
| `app/api/routes.py` | 删除 | 删除耦合旧解析与双库检索的业务路由。 |
| `app/api/security.py` | 修改 | 签发固定 owner token，校验必需声明、发行者、受众和主体。 |
| `app/cli.py` | 修改 | 只保留交互生成密码哈希和数据库连通检查。 |
| `app/core/config.py` | 修改 | 移除模型与多用户配置，并在启动时验证访问凭证配置。 |
| `app/db/storage.py` | 删除 | 删除旧财务、多用户和 Chroma 存储逻辑。 |
| `app/main.py` | 修改 | 只装配认证、健康检查与启动验证。 |
| `app/rag/__init__.py` | 删除 | 移除旧 RAG 包入口。 |
| `app/rag/agent.py` | 删除 | 删除旧财务工具、文件卡片和 Agent 循环。 |
| `app/rag/answer.py` | 删除 | 删除旧单向量 RAG 基线。 |
| `app/rag/process.py` | 删除 | 删除以财务字段提取为中心的解析和摘要向量化。 |
| `app/rag/service.py` | 删除 | 删除旧双库存取和入库编排。 |
| `app/requirements.txt` | 修改 | 移除旧模型、向量库、上传和任务队列依赖，没有新增生产依赖。 |
| `app/tests/test_storage_security.py` | 删除 | 移除针对已删除 SQL builder 的测试，由新边界测试接替。 |
| `app/worker/__init__.py` | 删除 | 移除旧 worker 包入口。 |
| `app/worker/celery_app.py` | 删除 | 删除旧 Celery 配置，后续随新任务模型重新选择执行方案。 |
| `app/worker/tasks.py` | 删除 | 删除旧文件入库任务。 |
| `db/init/01_schema.sql` | 删除 | 删除旧 schema 初始化源码，不对已有数据库执行任何删除。 |
| `db/init/02_migration.sql` | 删除 | 删除旧迁移源码，不修改已有数据。 |
| `docker-compose.yml` | 修改 | 保留三个基础服务及 pgdata 卷，原文件挂载为只读。 |
| `frontend/index.html` | 修改 | 更新为个人知识库标题。 |
| `frontend/nginx.conf` | 修改 | 保留同源代理和登录限流，删除旧上传相关配置。 |
| `frontend/src/App.tsx` | 修改 | 简化应用外壳，服务端校验 owner 会话后显示工作区。 |
| `frontend/src/api.ts` | 修改 | 只保留登录、会话与健康请求。 |
| `frontend/src/components/FileDetailModal.tsx` | 删除 | 删除依赖旧字段和预览接口的详情弹窗。 |
| `frontend/src/i18n.ts` | 修改 | 仅保留当前页面中英文文案，并移除体验账户配置。 |
| `frontend/src/index.css` | 修改 | 清理旧业务样式，保留 PC 和移动端单栏骨架。 |
| `frontend/src/main.tsx` | 修改 | 仅注册登录和工作区路由，旧链接回到工作区。 |
| `frontend/src/pages/ChatPage.tsx` | 删除 | 删除旧对话与文件卡片页面。 |
| `frontend/src/pages/DocumentsPage.tsx` | 删除 | 删除依赖财务字段的文件列表。 |
| `frontend/src/pages/LoginPage.tsx` | 修改 | 简化为单密码登录，移除邮箱、注册与体验账户。 |
| `frontend/src/pages/TracesPage.tsx` | 删除 | 删除旧 Agent 轨迹页面，等待新调用模型。 |
| `frontend/src/pages/UploadPage.tsx` | 删除 | 删除旧上传轮询和手机拍照入口。 |
| `frontend/src/store.ts` | 修改 | 移除用户对象，改用独立 owner token 键并清理旧会话。 |
| `README.md` | 新增 | 新增当前状态、结构、验证命令和文档入口。 |
| `app/api/health.py` | 新增 | 新增独立 readiness 路由，数据库异常返回 503。 |
| `app/db/connection.py` | 新增 | 新增只执行 SELECT 1 的数据库检查。 |
| `app/tests/test_shell.py` | 新增 | 新增 8 项认证、配置、路由撤除和健康状态回归测试。 |
| `frontend/src/pages/WorkspacePage.tsx` | 新增 | 新增明确标识待开放能力的工作区骨架和真实服务状态。 |
| `docs/REBUILD.md` | 新增 | 记录已确认范围、重建顺序和数据迁移边界。 |
| `docs/CLEANUP.md` | 新增 | 记录本次各文件的新增、修改和删除。 |

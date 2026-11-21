# Production deployment

Main branch pushes run the full PostgreSQL, OCR, frontend and browser suite before deployment. A failed test prevents all production changes.

GitHub Actions transfers the exact tested commit to `$DEPLOY_PATH/.releases/<commit>`. The original server checkout and its local modifications remain intact. Production keeps the existing application network, loopback frontend port, dedicated Caddy HTTPS route, Google ADC mounts, database volume and original files.

The initial owner password is generated outside git; only its bcrypt verifier is stored in `bootstrap-owner.hash`. Subsequent releases preserve the configured owner hash. A weak legacy JWT secret is rotated on the server. Neither environment values nor passwords are printed in deployment logs.

Images build before stopping the old app. A timestamped private `.backups` directory holds resolved rollback configuration, frozen image tags, original environment, git diff, verified PostgreSQL dump and original-file archive. Original files are read through a read-only bind in a temporary container so root-owned 0600 uploads can be backed up without changing their permissions. Database migration creates only the additive `knowledge_base_v1` namespace. Legacy records are retained but are not imported into the MVP interface.

The embedding release switches the database image to `pgvector/pgvector:0.8.7-pg16-trixie`, preserving PG16's exact volume, environment and network configuration. Pulling images and building applications happen before downtime. After backing up the old database, the new PG16 container must pass readiness and extension-availability checks before migrations. A failed database startup restores the frozen old PG16 image; after a successful migration, application rollback retains the healthy pgvector image so the extension remains available.

After cutover, checks exercise authentication enforcement, upload, parsing, chunks, pgvector migration, independent embedding state, keyword search, authenticated MCP discovery/search/context reads, byte-exact original download and public HTTPS health. The unique test document is removed. Any failure after stopping the old application restores its frozen application images and configuration. No image or volume pruning is performed. Cloud embedding readiness is explicitly reported; a missing Vertex API or IAM permission does not invalidate readable documents.

The release derives `MCP_PUBLIC_URL` from the preserved Caddy hostname, so the SDK accepts the real public Host/Origin without disabling DNS rebinding protection. MCP tools use a separate read-only JWT audience; no answer model is needed for deployment verification. See [MCP setup](../docs/MCP.md) for client credentials.

The active release is `$DEPLOY_PATH/.current-release`. Use its `production.json` with project name `rag-system` for operations; the original root compose file intentionally remains the legacy configuration.

Example status command on the server:

```sh
docker compose -p rag-system -f "$DEPLOY_PATH/.current-release/production.json" ps
```

To roll back manually, choose the desired `.backups/<timestamp>-<commit>/rollback.json` and run `docker compose -p rag-system -f <file> up -d --no-deps --no-build app frontend`, adding `celery_worker` only for legacy releases. Repoint `.current-release` to the restored release for an MVP rollback, or remove only that symlink for a legacy rollback. Database restoration is normally unnecessary because migration is additive; never overwrite production data with a dump without reviewing subsequent writes.

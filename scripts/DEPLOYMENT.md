# Production deployment

Main branch pushes run the full PostgreSQL, OCR, frontend and browser suite before deployment. A failed test prevents all production changes.

GitHub Actions transfers the exact tested commit to `$DEPLOY_PATH/.releases/<commit>`. The original server checkout and its local modifications remain intact. Production keeps the existing application network, loopback frontend port, dedicated Caddy HTTPS route, Google ADC mounts, running PostgreSQL container, database volume and original files.

The initial owner password is generated outside git; only its bcrypt verifier is stored in `bootstrap-owner.hash`. Subsequent releases preserve the configured owner hash. A weak legacy JWT secret is rotated on the server. Neither environment values nor passwords are printed in deployment logs.

Images build before stopping the old app. A timestamped private `.backups` directory holds resolved rollback configuration, frozen image tags, original environment, git diff, verified PostgreSQL dump and original-file archive. Original files are read through a read-only bind in a temporary container so root-owned 0600 uploads can be backed up without changing their permissions. Database migration creates only the additive `knowledge_base_v1` namespace. Legacy records are retained but are not imported into the MVP interface.

After cutover, checks exercise authentication enforcement, upload, parsing, chunks, byte-exact original download and public HTTPS health. The unique test document is removed. Any failure after stopping the old application restores its frozen application images and configuration. Redis and Chroma are stopped after success; their containers and data volumes are retained. No image or volume pruning is performed.

The active release is `$DEPLOY_PATH/.current-release`. Use its `production.json` with project name `rag-system` for operations; the original root compose file intentionally remains the legacy configuration.

Example status command on the server:

```sh
docker compose -p rag-system -f "$DEPLOY_PATH/.current-release/production.json" ps
```

To roll back manually, choose the desired `.backups/<timestamp>-<commit>/rollback.json` and run `docker compose -p rag-system -f <file> up -d --no-deps --no-build app frontend`, adding `celery_worker` only for legacy releases. Repoint `.current-release` to the restored release for an MVP rollback, or remove only that symlink for a legacy rollback. Database restoration is normally unnecessary because migration is additive; never overwrite production data with a dump without reviewing subsequent writes.

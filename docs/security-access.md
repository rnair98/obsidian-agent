# Workflow access and local deployment

Workflow requests require `Authorization: Bearer <token>`. Configure one
high-entropy `SECURITY__WORKFLOW_TOKEN` for this single-user service. Missing
server configuration returns 503; missing or incorrect credentials return 401.
No unauthenticated development bypass exists. Health and OpenAPI remain public.
For access beyond localhost, terminate TLS and enforce access at the deployment
boundary. This shared token does not provide separate tenant identities.

## Local process

Choose an absolute, canonical vault path owned by the service user. Both
allowlists default to empty. A local request must match an approved vault
exactly; allowing a parent does not allow arbitrary descendants. Symlink aliases
and relative paths are rejected. Vault directories must not be writable by
untrusted local users: path checks do not eliminate concurrent filesystem races.

```sh
export SECURITY__WORKFLOW_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export SECURITY__LOCAL_VAULTS='["/absolute/path/to/Vault"]'
export SECURITY__GIT_REPOSITORIES='[]'
just run
```

Keep the token out of shell tracing, logs and source control. If using `.env`,
set restrictive permissions and retain existing provider configuration. Lists
use JSON. Clients must include the header on every workflow request:

```sh
curl -sS http://127.0.0.1:8000/api/v1/workflows/run/research \
  -H "Authorization: Bearer $SECURITY__WORKFLOW_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"topic":"research topic","vault":{"type":"local","path":"/absolute/path/to/Vault"}}'
```

## Git vaults

Git vaults are disabled until an exact canonical public GitHub HTTPS repository
URL is approved, for example:

```sh
export SECURITY__GIT_REPOSITORIES='["https://github.com/owner/vault.git"]'
```

HTTP, SSH, file paths, URL credentials, query strings, fragments and arbitrary
hosts are rejected, even if accidentally placed in the allowlist. Each fetch
uses the approved URL explicitly, never every cached remote. Git processes use
an empty temporary HOME, no system/global Git config, no inherited proxy or
credential environment, no hooks, HTTPS-only transport, TLS verification and
disabled redirects. Cached config is checked against a small safe schema before
Git reads it; extra includes, URL rewrites, credential helpers and hooks fail
closed. Private repositories requiring ambient credentials are unsupported.

This constrains the Git vault transport. It is **not a process-wide egress
firewall**: LLM, MCP, Jina and GitHub tool integrations retain their existing
network paths. A shared/production deployment needs an external egress policy
covering those integrations too. Git caches must be owned by the service user;
hostile concurrent local cache mutation is outside this boundary.

## Compose and standalone containers

Compose publishes the API and Phoenix UI on IPv4 loopback. Postgres and the
collector have no host ports. Compose requires `POSTGRES_PASSWORD` and
`SECURITY__WORKFLOW_TOKEN`; it no longer supplies a default database password.
Use a generated URL-safe database password because the Compose connection URI
contains it. Do not print resolved Compose configuration containing credentials.

Compose's local vault allowlist is deliberately empty: container paths and
writable vault mounts must be configured explicitly before enabling local vaults.
Git allowlisting is passed through from `SECURITY__GIT_REPOSITORIES`, but writable
managed-cache storage is still required. These source changes do not restart or
reconfigure an existing stack, database, firewall or persisted credentials.
Recreating an existing database with a new environment value does not rotate
its initialized password; use a separate controlled rotation if needed.

`just db-up` requires an exported `POSTGRES_PASSWORD` and publishes port 5432
only on localhost. `just phoenix` binds its UI and collector to localhost.

## Verification and rollback

Tests reject missing/wrong credentials before execution, unapproved local paths,
symlink aliases, non-approved Git destinations and cached URL rewrites. They
also verify the Git process environment does not inherit proxy/Git overrides.
Positive tests cover approved local access and a simulated approved Git vault;
they do not contact GitHub or paid model providers.

Before deployment, configure credentials and approved paths, run tests, and
review the saved security diff. Rollback means reverting only that diff and
restoring the prior local configuration. No database or user vault migration is
part of this change. Reverting reintroduces the access-boundary findings.

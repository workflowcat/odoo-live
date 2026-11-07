# Maintainers

- Andrii Udovychenko - GitHub `workflowcat`, Bot&Partners

## How code moves (maintainers only)

The upstream repository is Cloudflare Artifacts `own/odoo-live`; GitHub `workflowcat/odoo-live` is its
mirror. Nobody pushes to GitHub directly: the mirror refuses to update if GitHub moved on its own.

```bash
./scripts/check_static.sh && ./scripts/test_full.sh   # or wait for CI on the pull request
CFGIT_NS=own cfgit push                               # all branches to Artifacts own/odoo-live
cfmirror own/odoo-live workflowcat/odoo-live          # then the GitHub mirror, never forced
```

Landing an outside pull request: fetch its branch, merge it into `main` locally (keep the author),
run the checks, push and mirror as above. GitHub then marks the pull request as closed by that commit;
say so in a comment.

Pushing deploys nothing. Servers take code when someone runs `deploy/deploy.sh` on them; it pulls from
GitHub, so mirror first.

## Releases

Tag `main` as `19.0.YYYY.MM.DD` when `CHANGELOG.md` has something worth announcing; copy that section
into the GitHub release notes.

## Moving the bridge to one token per environment

The bridge Worker (`worker/`) accepts scoped tokens from 2026-11-07; until its `BRIDGE_TOKENS` secret is
set it still takes the old shared `BRIDGE_TOKEN`. To switch:

1. `cd worker && node scripts/new-token.mjs prod "GET /api/odb/" "* /api/kyc/"`, then the same for
   `staging "GET /api/odb/screen/" "GET /api/kyc/"` and, if the container stand is used, `stand ...`.
   Keep each printed token in the secret manager; never in a file in this repository.
2. Put the printed entries, as one JSON list, into the Worker secret `BRIDGE_TOKENS` and deploy the Worker.
   From that moment the old `BRIDGE_TOKEN` stops working.
3. Give each Odoo its own token as `BP_BRIDGE_TOKEN` in `deploy/env.<env>` and set `BP_BRIDGE_URL`
   there explicitly (the server compose file no longer has a default); redeploy staging, then prod.
4. Rotate: add the new entry, deploy, switch Odoo, remove the old entry, deploy.

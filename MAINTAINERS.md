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

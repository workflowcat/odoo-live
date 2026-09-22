#!/bin/bash
# Refresh the Cloudflare token Odoo uses for Workers AI on the local stand.
# "Your account for now": the wrangler OAuth login of this Mac (scope ai:write). It expires; rerun before a session.
# For a stable token, create an API token with Workers AI permission and set CF_API_TOKEN in .env instead.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
umask 077
(cd "$here/worker" && npx wrangler auth token --json 2>/dev/null) | python3 -c 'import sys,json; print(json.load(sys.stdin)["token"], end="")' > "$here/.cf/token.tmp"
mv "$here/.cf/token.tmp" "$here/.cf/token"
echo "token refreshed: $here/.cf/token ($(wc -c < "$here/.cf/token") bytes)"

#!/usr/bin/env bash
# Every check that needs no database and no Docker, in one run. CI runs this first.
#
#   scripts/check_static.sh
#
# 1. layers_check.py    logic modules carry no UI code; menus only in l10n_ua_navigation
# 2. contract_check.py  docs/api describes the code as it is
# 3. words_check.py     UI words follow docs/payroll/words.md
# 4. manifest_check.py  manifests, licenses, pinned OCA sources, no defaults pointing at our servers
#    catalog_check.py   industry packs (addons/*/catalog/*.json): format, references, codes, barcodes
# 5. Python syntax of every module and script (needs Python 3.10+, Odoo 19's minimum)
# 6. ruff (ruff.toml)    undefined and unused names in our modules and scripts; skipped without ruff
# 7. js tests           bridge token scopes, assistant sign-in (node --test, no npm install); skipped without Node
set -uo pipefail
cd "$(dirname "$0")/.."

FAILED=0
run() {
    local name="$1"; shift
    if out="$("$@" 2>&1)"; then
        echo "PASS  $name  $(printf '%s\n' "$out" | grep -v '^\s*$' | tail -1)"
    else
        echo "FAIL  $name"
        printf '%s\n' "$out" | tail -20 | sed 's/^/      /'
        FAILED=1
    fi
}

run layers   python3 scripts/layers_check.py
run contract python3 scripts/contract_check.py
run words    python3 scripts/words_check.py
run manifest python3 scripts/manifest_check.py
run catalog  python3 scripts/catalog_check.py
if python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
    run syntax python3 -m compileall -q addons scripts reference
else
    echo "SKIP  syntax  (Python 3.10+ needed, found $(python3 -V 2>&1))"
fi

LINT_PATHS=(addons/l10n_ua_* addons/bp_* scripts reference)
if command -v ruff >/dev/null; then
    run lint ruff check --quiet "${LINT_PATHS[@]}"
elif command -v uvx >/dev/null; then
    run lint uvx ruff check --quiet "${LINT_PATHS[@]}"
else
    echo "SKIP  lint    (install ruff: pip install ruff)"
fi

if command -v node >/dev/null; then
    run js     node --test worker/test/*.test.mjs assistant/test/*.test.mjs
else
    echo "SKIP  js      (Node 18+ needed)"
fi

exit $FAILED

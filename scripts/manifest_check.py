# -*- coding: utf-8 -*-
"""Manifests, licenses and links to our own infrastructure. No database needed.

Checks:
1. Every module in addons/ has a readable manifest with a version 19.0.x.y.z, an author
   and a license from the allowed set.
2. Every license a manifest uses has its full text in LICENSES/, and LICENSE exists.
3. Every vendored OCA module has its source commit pinned in addons/OCA_*.commit.
4. Our modules carry no default that points at our own servers: such addresses
   belong in .env or deploy/, never in a module.
5. Bundled fonts ship with a license file next to them.

Prints a note (not a failure) for each own LGPL-3 module that pulls an AGPL-3 module:
a full install is then covered by AGPL-3, as the README says.

Run: python3 scripts/manifest_check.py
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDONS = os.path.join(ROOT, "addons")
ALLOWED = {"LGPL-3": "LGPL-3.0.txt", "AGPL-3": "AGPL-3.0.txt", "GPL-3": "GPL-3.0.txt"}
OWN_PREFIXES = ("l10n_ua_", "bp_")
# Hosts that belong to us. A module may name them in a comment, never as a default value.
OUR_HOSTS = re.compile(r"https?://[a-z0-9.-]*(botpartners\.workers\.dev|bnp\.works|bot-partners\.com)")
VERSION = re.compile(r"^19\.0\.\d+\.\d+\.\d+$")

problems = []
notes = []


def load(module):
    path = os.path.join(ADDONS, module, "__manifest__.py")
    with open(path, encoding="utf-8") as fh:
        return ast.literal_eval(fh.read())


modules = {}
for name in sorted(os.listdir(ADDONS)):
    if os.path.isfile(os.path.join(ADDONS, name, "__manifest__.py")):
        try:
            modules[name] = load(name)
        except (SyntaxError, ValueError) as exc:
            problems.append("%s: manifest is not a plain literal (%s)" % (name, exc))

own = [m for m in modules if m.startswith(OWN_PREFIXES)]
vendored = [m for m in modules if m not in own]

# 1. manifest basics
for name, man in modules.items():
    if not VERSION.match(str(man.get("version", ""))):
        problems.append("%s: version %r is not 19.0.x.y.z" % (name, man.get("version")))
    if not man.get("author"):
        problems.append("%s: no author" % name)
    if man.get("license") not in ALLOWED:
        problems.append("%s: license %r is not one of %s" % (name, man.get("license"), ", ".join(sorted(ALLOWED))))

# 2. license texts
if not os.path.isfile(os.path.join(ROOT, "LICENSE")):
    problems.append("LICENSE is missing")
for lic in sorted({m.get("license") for m in modules.values()} & set(ALLOWED)):
    if not os.path.isfile(os.path.join(ROOT, "LICENSES", ALLOWED[lic])):
        problems.append("LICENSES/%s is missing (used by %s modules)" % (ALLOWED[lic], lic))
if "LGPL-3" in {m.get("license") for m in modules.values()} and not os.path.isfile(
        os.path.join(ROOT, "LICENSES", "GPL-3.0.txt")):
    problems.append("LICENSES/GPL-3.0.txt is missing (LGPL-3 builds on it)")

# 3. vendored modules are pinned
pinned_repos = {f[4:-7].replace("_", "-") for f in os.listdir(ADDONS) if f.startswith("OCA_") and f.endswith(".commit")}
for name in vendored:
    website = modules[name].get("website", "")
    repo = website.rstrip("/").rsplit("/", 1)[-1] if "github.com/OCA/" in website else ""
    if not repo:
        problems.append("%s: vendored module without an OCA website in its manifest" % name)
    elif repo not in pinned_repos:
        problems.append("%s: no addons/OCA_%s.commit pins its source" % (name, repo.replace("-", "_")))

# 4. no defaults pointing at our servers inside our modules
for name in own:
    for base, _dirs, files in os.walk(os.path.join(ADDONS, name)):
        if os.sep + "tests" in base:
            continue
        for fname in files:
            if not fname.endswith((".py", ".xml", ".js", ".csv")):
                continue
            path = os.path.join(base, fname)
            with open(path, encoding="utf-8", errors="replace") as fh:
                for lineno, line in enumerate(fh, 1):
                    code = line.split("#", 1)[0] if fname.endswith(".py") else line
                    if OUR_HOSTS.search(code):
                        problems.append("%s:%d: points at our own server; read it from the environment"
                                        % (os.path.relpath(path, ROOT), lineno))

# 5. fonts carry their license
for base, _dirs, files in os.walk(ROOT):
    if "/.git" in base or "node_modules" in base:
        continue
    if any(f.endswith((".woff", ".woff2", ".ttf", ".otf")) for f in files):
        if not any(f.upper().startswith(("OFL", "LICENSE")) for f in files):
            problems.append("%s: fonts without a license file" % os.path.relpath(base, ROOT))


# note: LGPL modules whose install pulls AGPL modules
def closure(module, seen):
    for dep in modules.get(module, {}).get("depends", []):
        if dep in modules and dep not in seen:
            seen.add(dep)
            closure(dep, seen)
    return seen


agpl = {m for m, man in modules.items() if man.get("license") == "AGPL-3"}
for name in own:
    if modules[name].get("license") == "LGPL-3" and closure(name, set()) & agpl:
        notes.append(name)

print("Modules: %d (own %d, vendored %d)" % (len(modules), len(own), len(vendored)))
if notes:
    print("Note: %d own LGPL-3 modules pull AGPL-3 modules; a full install is covered by AGPL-3." % len(notes))
if problems:
    print("\n".join("FAIL " + p for p in problems))
    print("Problems: %d" % len(problems))
    sys.exit(1)
print("All manifest and license checks passed.")

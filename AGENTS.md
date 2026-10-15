# odoo-live - agent guidance

Read README.md and existing component instructions before implementation.

## Source and delivery default (2026-10-15)

Follow the [shared delivery policy](https://github.com/bnp-team/skills/blob/72258831a9e5afaee9a9e5159241955df0cc4421/docs/cloud-delivery.md); on Andrii's Mac it is in `~/.claude/AGENTS.md` (also loaded by Codex).

- Target: Cloudflare Artifacts Git primary, Cloudflare builds/deployment for compatible components, GitHub mirror/review surface. Active Artifacts access, runner connection and cutover are **unverified** here; keep the existing pipeline and source until parity is evidenced.
- Record exact source SHA, build/test logs, artifact/version and environment. Use isolated test bindings/data, preserve independent human release approval where required, and verify database backup/restore and migration recovery before stateful releases.
- Native Artifacts main builds deploy by default; this policy does not authorize connecting live triggers, merging, deploying, new credentials/access or disabling legacy workflows. Commands elsewhere in this file remain recipes subject to these gates.
- Runtime exception (owner: Andrii/project maintainer): Odoo 19 CE and PostgreSQL retain Docker/service runtime and their existing test runner. Workers is not a drop-in Odoo runtime. Re-evaluate only after a separately reviewed architecture and database migration plan.

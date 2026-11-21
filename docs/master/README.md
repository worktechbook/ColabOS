# ColabOS v1.1.8 - Docs Index

Start here depending on who you are:

| Reader | Start with |
|---|---|
| Human user, first time | `docs/master/User_Manual.md` |
| Operator / troubleshooter | `docs/master/Architecture.md` |
| Autonomous agent (zero prior context) | `docs/master/Agent.md` (single source of truth) |

## Services (3)

| Name | Type | Version | Hash | Docs |
|---|---|---|---|---|
| devtools | tool | 1.0.0 | `a92aed243b76f7dc` (deterministic tar) | `docs/devtools/{README,Build_Log,User_Manual}.md` |
| tailscale-ssh | server | 1.2.3 (ships tailscale v1.104.5) | `1d324134bdbbe442` | `docs/tailscale-ssh/{README,Build_Log,User_Manual}.md` |
| oh-my-pi | tool | 19.0.1 | `f93076d1a2cb38dc` | `docs/oh-my-pi/{README,Build_Log,User_Manual}.md` |

## Engine commands (v1.1.8)

`svc bootstrap | doctor [--fix] | list [-m] | status [name] [-m] | install <name> [--force] | snapshot <name> [--version V] | logs <name> | doc-table [--json]`

Engine self-test (read-only, 145 checks):

```bash
python3 /content/drive/MyDrive/ColabOS/engine/selftest.py
```

The mandatory new-service flow lives in `docs/master/Agent.md` §6.

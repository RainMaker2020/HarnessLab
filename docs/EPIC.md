# Epic — module-scale work

Define top-level modules here. The Master Orchestrator runs one **Sub-Orchestrator** per unchecked `MODULE_*` line under `workspace/modules/<slug>/`.

## Modules

- [ ] MODULE_01: Database — schemas and persistence
- [ ] MODULE_02: API — HTTP surface
- [ ] MODULE_03: Frontend — UI

## Global Interface Contracts

Optional: add a `###` subsection per module with signatures other modules must rely on.

### MODULE_01

```text
// Example: define tables, migrations, and repository interfaces here.
```

### MODULE_02

```text
// Example: REST routes and request/response DTOs.
```

### MODULE_03

```text
// Example: props/callbacks the UI exposes to the shell app.
```

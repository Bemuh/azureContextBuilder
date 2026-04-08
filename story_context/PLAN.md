# Sync-Based CRUD for Azure DevOps Tasks (Backlog-Derived Parents, Safer Semantics)

## Summary
Provide a single `sync` workflow that pulls Tasks under selected parent backlog items, lets users edit a spreadsheet, and applies create/update/delete with explicit `Action`, conflict protection (`ServerRev`), minimal API calls, and robust Azure DevOps semantics. This revision adds field schema caching, create/link ordering, explicit pull field selection, clear-field semantics, core vs maybe enforcement, duplicate-child handling, conflict baseline behavior, and run manifest output.

---

## Goals
- One model: `sync pull -> sync plan -> sync push` (or `sync` alias).
- Explicit row intent; no inference.
- Safe edits: validation, protected columns, baseline integrity checks, lockfile.
- Fast apply: no per-row GETs except batch rev checks.
- Azure-specific correctness: link traversal, identity resolution, transitions, soft delete.

## Non-Goals
- Arbitrary work item types beyond Task (future).
- Reparenting tasks (future).

---

## UX / CLI

### Commands
- `sync pull`  
  Pull tasks under selected parents and update spreadsheet.
- `sync plan --file <file>`  
  Compute changes locally; write plan output into the same file.
- `sync push --file <file>`  
  Recompute local plan internally and apply changes to ADO; update Result/ServerRev/baseline.
- `sync`  
  Alias: if file missing -> `pull`; else -> `plan`.

### Key flags
- `--profile <name>`
- `--file <path>`
- `--format excel|csv|json` (default `excel`)
- `--include-done` (default false)
- `--delete-mode none|soft|hard` (default `none`)
- `--confirm-delete` (required for hard delete)
- `--force` (override conflict check)
- `--fail-fast` / `--max-errors N`
- `--read-only` (plan-only; no workbook writes)
- `--dry-run` (global; see behavior below)
- `--no-artifacts` (optional; do not write plan.json or sync_run.json)
- `--lockfile` (default on for push)
- `--setup-only`, `--no-setup`, `--allow-probe-write`
- `--transition-path <name>` (optional; see config)
- `--scope active|changed`, `--since <date>`
- `--chunk-size <N>` (advanced; default 200; auto-reduce on 413/400 size errors)
- `--allow-duplicates` (allow the same child under multiple parents; default off)
- `--cleanup-on-link-fail` (optional; soft-delete orphan on link failure)
- `--allow-clear` (enable clearing of fields marked clearable)

### Delete defaults
- Default `--delete-mode none`
- Recommended `--delete-mode soft` (if configured)
- `--delete-mode hard` requires `--confirm-delete`

### Dry-run behavior (global)
- `--dry-run` implies `--read-only`.
- Precedence: if both are set, treat as `--dry-run`.
- `sync plan --dry-run`: compute plan only; **no workbook writes**.
- `sync push --dry-run`: compute plan only; **no ADO writes** and **no workbook writes**.
- `sync pull --dry-run`: error ("dry-run not applicable to pull").
- Artifacts (`plan.json`, `sync_run.json`) still emit unless `--no-artifacts`.

### Read-only behavior
- `sync plan --read-only`: plan-only; no workbook writes.
- `sync push --read-only`: error ("read-only is plan-only; use --dry-run for push").

---

## Parent Discovery (Decision Complete)

### Canonical method: link traversal (direct children only)
Run a link query per parent, then filter locally:

```
SELECT [System.Id]
FROM WorkItemLinks
WHERE
  ([Source].[System.Id] = <PARENT_ID>
   OR [Target].[System.Id] = <PARENT_ID>)
  AND [System.Links.LinkType] = 'System.LinkTypes.Hierarchy-Forward'
MODE (MustContain)
```

**Local filter rule (explicit XOR):**
- Accept only if exactly one side is the parent:
  - `(Source.Id == parent) XOR (Target.Id == parent)`
- Then require the non-parent side is Task:
  - If `Source.Id == parent` and `Target.WorkItemType == Task` -> child = `Target.Id`
  - If `Target.Id == parent` and `Source.WorkItemType == Task` -> child = `Source.Id`
- Else ignore
- If WIQL returns >0 relations but XOR filter yields 0 tasks, emit `WARNING (no Task children after filtering; check hierarchy link usage)`

Only direct children (no multi-level traversal).

### Duplicate child handling
- If a child Task appears under multiple selected parents:
  - Default: place it under the first parent (profile order if available, otherwise numeric parent id), emit warning
  - `--allow-duplicates`: duplicate rows across parents, but duplicates must be `Action=NOOP` on all but one row.

---

## Parent Allowlist (Backlog-Derived)

### Derivation output
- `allowed_parent_types: [...]`
- `default_parent_type: <type>`

### Derivation behavior
- Fetch backlog configuration once per project per run, cache results.
- If detection fails -> fallback to `["Product Backlog Item", "User Story", "Requirement"]`.
- Allow override in `profiles.yml`.

---

## Field Schema Cache (New)

### File
- `config/<org>/<projectId>/fields_cache.json`

### Contents
`refName -> { type, readOnly, isIdentity, isPicklist, allowedValues?, isRequired? }`

### Behavior
- `pull` refreshes once per run (or if older than N days).
- If field type changes between runs -> `PlanStatus=WARNING (schema changed; re-pull recommended)`.

---

## Spreadsheet Design (Excel)

### Visible columns
- `Action` (`CREATE|UPDATE|DELETE|NOOP`)
- `WorkItemId`
- `Title`, `Description`, `OriginalEstimate`, `CompletedWork`, `State`
- `StartDate`, `FinishDate`, `DueDate`, `AssignedTo`
- Required-on-Done fields
- `Plan`, `PlanStatus`, `Result`
- `LastSyncedAt`, `LastSyncedBy`, `ServerRev`

### Hidden metadata
- Per sheet: `ParentId`, `ParentTitle`
- `FieldMap` sheet: `DisplayName`, `ReferenceName`
- `__resolved_AssignedTo` (canonical ADO identity string)
- `__resolve_status_AssignedTo` (OK/AMBIGUOUS/NOT_FOUND + message)

### Baseline storage
- Hidden `__base_<Field>` columns
- `__base_checksum` per row

### Validations and protection
- Dropdowns for `Action` and `State`
- Numeric/date validation
- Protect `WorkItemId`, `ParentId`, `ServerRev`, `Plan`, `PlanStatus`, `Result`,
  baseline columns, `FieldMap`, `__resolved_AssignedTo`, `__resolve_status_AssignedTo`
- Sheets formatted as Excel Tables

---

## CSV/JSON

### CSV
- Flat file with `ParentId`
- No baseline columns in editable file

### Baseline sidecar
- `<file>.baseline.json`
- `plan/push` auto-load sidecar

---

## Baseline and Checksum (Decision Complete)

### Normalization
- Strings: `strip()` only (no internal whitespace collapse)
- Description/HTML/markdown fields: treat as raw string; trim only
- Newlines: normalize `\r\n` and `\n` to `\n` inside the tool before checksum and writeback
- Dates: normalize to UTC ISO where appropriate (see Date Rules)
- Numbers: canonical string form
- Empty/null: empty string

### Checksum input (canonical JSON)
- Ordered JSON `{refName: normalizedValue, ...}` sorted by key
- Minified UTF-8 JSON string
- SHA-256 stored in `__base_checksum`

### Behavior
- If checksum mismatch on plan/push -> fail row with "baseline tampered; re-pull"

---

## Plan vs Push Writeback

### `pull`
- Clears `Plan`, `PlanStatus`, `Result`
- Clears `__resolved_AssignedTo` and `__resolve_status_AssignedTo`
- Re-resolves identities after pull and fills `__resolve_status_AssignedTo`

### `plan`
- Writes:
  - `Plan` (diff summary)
  - `PlanStatus` (`PLANNED`, `WARNING`, `NOOP`)
- Does not change baseline or visible fields
- `--read-only`: no workbook writes; print plan and optionally emit `plan.json`
- Artifacts are still emitted unless `--no-artifacts`

### `push`
- Always recomputes local plan from baseline
- Writes:
  - `Result` (`OK/FAILED/SKIPPED + message`)
  - `ServerRev` (new)
  - baseline for changed fields + checksum
  - `LastSyncedAt`, `LastSyncedBy`
  - canonicalized values (dates, identities)

### Run manifest
- Emit `<file>.sync_run.json` on plan/push:
  - run_id, timestamp, org/project, profile, counts, warnings, chunk size, summary
- Emitted even in `--read-only` / `--dry-run` unless `--no-artifacts`
- Optional: emit `<file>.plan.json` from `plan` / `push --dry-run` when requested (machine-readable per-row plan)

---

## Conflict Detection

### Batch rev fetch
- WIQL with `IN`, chunk size `--chunk-size`
- Retry/backoff; auto-reduce on 413 and 400 "too large"

### Behavior
- If mismatch -> skip row, do not update baseline, set `Result=CONFLICT (rev mismatch); re-pull`
- `--force` overwrites server state using user edits; hard deletes still require `--confirm-delete`

---

## Identity Resolution (Decision Complete)

### Priority
1. Exact email match
2. Exact unique display name match
3. Fail with "ambiguous identity" + candidates

### API + storage
- Use Graph/Identity search endpoint
- Cache results per run
- On plan: pre-resolve and write `__resolve_status_AssignedTo`
- On push: send resolved identity value; write back visible `AssignedTo` + hidden resolved value

---

## Writable Fields Allowlist (Task)
Maintain an internal allowlist of writable fields:
- `System.Title`
- `System.Description`
- `System.State`
- `System.AssignedTo`
- `Microsoft.VSTS.Scheduling.OriginalEstimate`
- `Microsoft.VSTS.Scheduling.CompletedWork`
- `Microsoft.VSTS.Scheduling.StartDate`
- `Microsoft.VSTS.Scheduling.FinishDate`
- `Microsoft.VSTS.Scheduling.DueDate`
- plus required-on-done fields if the field metadata marks them writable

If a column maps to a non-writable field:
- `PlanStatus=WARNING`
- Ignore on push

---

## Date/Time Rules
- Date-only fields -> store as `YYYY-MM-DD`, write as date-only if field type supports; else `YYYY-MM-DDT00:00:00Z`
- Datetime fields -> normalize to UTC ISO `YYYY-MM-DDTHH:MM:SSZ`
- Excel serials interpreted as local date/time, converted to UTC at write time
- Write back canonical UTC strings to avoid drift

---

## Clear-Field Semantics (New)
- Empty string means clear only if:
  - `--allow-clear` is set and
  - field is listed in `clearable_fields` config
- Otherwise empty = "leave unchanged"
- For `CREATE`, empty values are treated as "not provided" (field omitted) regardless of `--allow-clear`

Example:
```yaml
clearable_fields:
  - System.Description
  - Microsoft.VSTS.Scheduling.DueDate
```

---

## Action Rules (Decision Complete)
- `Action` blank -> `NOOP`
- `CREATE`: `WorkItemId` must be blank
- `UPDATE|DELETE`: `WorkItemId` required
- Duplicate `WorkItemId` in file -> fail fast
- Changing `ParentId` on UPDATE is not allowed (fail row)
- If `--allow-duplicates` is enabled, duplicates are only allowed when all but one duplicate row are `Action=NOOP`

---

## Create/Link Ordering (New)
For `CREATE` rows:
1. Create Task
2. Link Task to Parent using configured relation
3. If linking fails:
   - Default: mark row FAILED, do not delete created task
   - If `--cleanup-on-link-fail`: soft-delete orphan using soft delete config

---

## Soft Delete (Decision Complete)

### Config
```yaml
soft_delete:
  state: "Removed"
  reason_field: "Microsoft.VSTS.Common.ResolvedReason" # optional
  reason_value: "Soft deleted by sync"                 # optional
  tag: "soft-deleted-by-sync"                           # optional
```

### Behavior
- `--delete-mode soft`:
  - Transition to `soft_delete.state`
  - Add optional tag/reason
  - Validate required fields for target state if available
  - Otherwise attempt transition and surface server error on failure

---

## Required-on-Done Fields (Hybrid, Low-Write)

### Discovery order
1. Done-sample inference (read-only)
2. Rules-only discovery (read-only)
3. Probe-write (opt-in)

### Candidate field set (non-circular)
`candidate_fields` =
- core visible fields
- required fields discovered from rules (if available)
- fields referenced by transition paths or soft delete config

### Sample query mechanics
- Query `WorkItemType=Task` and `State=Done`
- Sample size: 10-30 (configurable)
- Prefer tasks changed recently; optionally `ChangedBy=current user`

### Revision snapshot preference
- Preferred: fields at revision where `State` first became Done
- Fallback: current snapshot if revisions unavailable

### Enforcement
- `core` missing -> block push
- `maybe` missing -> `PlanStatus=WARNING` only

---

## Pull Field Set Selection (New)

### Computed `pull_fields`
- Core visible fields (ref names)
- Required-on-done candidate fields
- Fields referenced by transition paths and soft delete config
- Always include: `System.Id`, `System.Rev`, `System.WorkItemType`, `System.Title`

### Degrade gracefully if too large
- Always keep core visible fields + `System.Rev`
- Drop lowest-priority optional fields with warning

---

## Atomicity per Row
- Each row is its own transaction boundary
- If a row fails, do not perform dependent operations for that row
- Continue unless `--fail-fast` or `--max-errors`

---

## Lockfile
- On `push`, create `<file>.lock` with run id + timestamp
- If lock exists -> fail unless `--force-lock`
- Remove on completion

---

## API Call Strategy (Minimize Round-Trips)

### Pull
- Parent selection -> link traversal -> child IDs
- Batch `/workitems?ids=...&fields=...` in chunks (`--chunk-size`)
- Retry/backoff on throttle

### Plan
- Local diff only (no ADO calls)

### Push
- Batch rev fetch via WIQL IN chunks
- PATCH/DELETE per row only

---

## Tests / Scenarios
- Pull returns direct child Tasks (forward links, filtered locally)
- Parent types derived from backlog config, cached per run
- Action blank -> NOOP
- Create/Update/Delete paths enforced; link failure behavior validated
- Conflict skip via rev mismatch; baseline unchanged
- Soft delete validates target-state requirements or fails with server message
- Baseline checksum mismatch fails row
- Identity pre-resolution flags ambiguous/not found before push
- `--read-only` plan emits no workbook changes
- Duplicate child across parents handled deterministically
- Clear-field semantics honored only for allowlisted fields

---

## Assumptions / Defaults
- Work item type = Task only
- Delete mode default = none
- Parent allowlist derived from backlog config; fallback broad
- Plan writes in place unless `--read-only`
- Conflict check required unless `--force`

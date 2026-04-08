# story_context

Downloads Azure DevOps user stories and turns them into organized Markdown files that any agent can read to generate test cases, documentation, or analysis.

All runtime state lives inside this folder:
- `story_context/config/profiles.yml`
- `story_context/keys/`
- `story_context/story_context_data/`
- `story_context/README.md`, `story_context/PLAN.md`, `story_context/AGENTS.md` for the digest

## How it works — the 4 commands

There are exactly four commands, and you always run them in this order:

```
list-stories  →  register  →  refresh  →  build-context
```

### 1. `list-stories` — preview what exists in ADO

Queries Azure DevOps and prints a table of stories. Nothing is saved to disk.
Use this to decide which stories or epics you want to work with.

```bash
py -m story_context list-stories --profile null \
  --area "Plataforma Virtual - NARP\Plataforma Virtual - Studia LMS V2" \
  --iteration "Plataforma Virtual - NARP"
```

Add `--parent-epic 215249` to filter to stories under a specific epic.
Add `--format json` to get JSON output instead of the default tab-separated table.

---

### 2. `register` — tell the tool which stories to track

Records the selected stories in a local registry file. Does **not** download story content yet — that happens in `refresh`.

**Option A — register specific IDs:**
```bash
py -m story_context register --profile null \
  --area "Plataforma Virtual - NARP\Plataforma Virtual - Studia LMS V2" \
  --iteration "Plataforma Virtual - NARP" \
  --ids 215250,215555,215556
```

**Option B — register all stories under an epic automatically:**
```bash
py -m story_context register --profile null \
  --area "Plataforma Virtual - NARP\Plataforma Virtual - Studia LMS V2" \
  --iteration "Plataforma Virtual - NARP" \
  --parent-epic 215249
```

Option B is more convenient when you want all stories for a given epic. It queries ADO for all stories that have that epic as their parent and registers them all at once, linked to the epic so `build-context --epic` works later.

If an ID doesn't exist in ADO, you get a warning but the valid IDs are still registered.

---

### 3. `refresh` — download story content from ADO

Fetches each registered story: its description, acceptance criteria, linked child tasks, and metadata. Writes 4 files per story into `story_context_data/corpus/`.

```bash
# Refresh all registered stories
py -m story_context refresh --profile null

# Or refresh only specific stories
py -m story_context refresh --profile null --ids 215250,215555
```

This is the only command that makes write API calls to your local disk. Run it again any time you want to pick up changes from ADO.

---

### 4. `build-context` — assemble a single Markdown file for an agent

Combines the project documentation + the story files into one `.md` file ready to hand to an agent.

```bash
# By epic (all stories registered under that epic)
py -m story_context build-context --profile null \
  --epic 215249 \
  --output context_epic_215249.md

# By specific IDs
py -m story_context build-context --profile null \
  --ids 215250,215555,215556 \
  --output context_selected.md
```

---

## What files get created

Running the full pipeline creates this folder structure under `story_context/story_context_data/`:

```
story_context/story_context_data/
│
├── registries/
│   └── null.yml                ← master list of all registered stories
│
├── project_digest/
│   └── null.md                 ← snapshot of README.MD + PLAN.md + AGENTS.md
│
├── index/
│   └── null.json               ← flat index: id, title, state, last_refreshed_at
│
├── corpus/
│   └── null/
│       └── 215250/             ← one folder per story ID
│           ├── story.md        ← the agent-facing Markdown file
│           ├── story.json      ← lossless raw snapshot of all ADO fields
│           ├── relations.json  ← parent epic ID + child task list
│           └── refresh_meta.json ← when it was fetched, how fields were converted
│
└── bundles/
    └── epic_215249_Instituciones_oficiales.md   ← final context file for agent use
```

### What each file is for

**`registries/null.yml`**
The registry. Lists every story you have registered, its current state, which epic it belongs to, and when it was last refreshed. Edited automatically by `register` and `refresh` — you don't need to touch it manually.

**`project_digest/null.md`**
A snapshot of the repo's own documentation (README.MD, PLAN.md, AGENTS.md) compiled into one file. Generated automatically on first `register`. Included at the top of every context bundle so the agent understands the project before reading the stories.

**`index/null.json`**
A compact flat list of all registered stories with id, title, state, epic, and last refresh timestamp. Rebuilt on every `refresh`. Useful for quick lookups without reading individual story files.

**`corpus/<profile>/<id>/story.md`**
The main agent-facing file for one story. Contains:
- A metadata block (id, type, state, area, iteration, fetched date)
- A metadata table (created by, changed by, dates)
- Acceptance criteria (from ADO, converted from HTML to Markdown)
- Description
- A table of linked child tasks (id, title, state)
- Source traceability (ADO URL, parent link, fetch timestamp)

**`corpus/<profile>/<id>/story.json`**
The complete raw ADO field snapshot. Kept for traceability — if you need to know the exact original value of any field, it's here. Not used for agent context directly.

**`corpus/<profile>/<id>/relations.json`**
Just the parent/child structure: parent epic ID and the list of direct child tasks with their id, title, state, and type. Used to build the linked task table in `story.md`.

**`corpus/<profile>/<id>/refresh_meta.json`**
Records when the story was fetched and how each rich-text field (Description, Acceptance Criteria) was converted. The `method` field will be `markitdown` if the optional markitdown library converted the HTML, or `fallback` if the built-in plain-text stripper was used instead.

**`bundles/epic_<id>_<name>.md`**
The final output — one file per epic, ready to be passed to an agent. Contains:
1. A manifest header (which stories are included)
2. The project digest
3. Every story's `story.md` content in ascending ID order
4. A JSON manifest block at the end listing all included/missing IDs

---

## Currently available bundles (Plataforma Virtual - Studia LMS V2)

| Epic | Bundle file | Stories |
|------|-------------|:-------:|
| Instituciones oficiales | `bundles/epic_215249_Instituciones_oficiales.md` | 21 |
| Plan de área | `bundles/epic_217701_Plan_de_área.md` | 27 |
| Instituciones privadas | `bundles/epic_217312_Instituciones_privadas.md` | 9 |
| Registro de Sesiones | `bundles/epic_216380_Registro_de_Sesiones.md` | 10 |
| Usuario Gestor de contenido | `bundles/epic_217675_Usuario_Gestor_de_contenido.md` | 3 |
| Automatizaciones | `bundles/epic_232519_Automatizaciones.md` | 5 |
| Spike studia versión escolar | `bundles/epic_192213_Spike_studia_versión_escolar.md` | 4 |
| Registros PO y PM | `bundles/epic_216684_Registros_PO_y_PM.md` | 4 |
| Diseño de la plataforma | `bundles/epic_234360_Diseño_de_la_plataforma.md` | 3 |
| Diseño y arquitectura | `bundles/epic_202877_Diseño_y_arquiectura.md` | 2 |

---

## How to use a bundle for test case generation

Open the relevant bundle file and pass it as context to an agent:

> Read `story_context_data/bundles/epic_215249_Instituciones_oficiales.md` and generate test cases for each user story. For each story use the acceptance criteria as the basis for the test scenarios.

Each bundle is self-contained — it includes the project context and all story details the agent needs.

---

## Re-running after ADO changes

Stories change in ADO as the sprint progresses. To update your local corpus:

```bash
# Re-download all stories (picks up new acceptance criteria, state changes, etc.)
py -m story_context refresh --profile null

# Then rebuild the affected bundle
py -m story_context build-context --profile null \
  --epic 215249 \
  --output story_context_data/bundles/epic_215249_Instituciones_oficiales.md
```

Only `refresh` makes network calls. `build-context` is a local file assembly operation.

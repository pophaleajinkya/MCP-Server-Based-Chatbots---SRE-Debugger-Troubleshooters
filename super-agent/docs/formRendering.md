# Dynamic Right-Panel Form Rendering — Full Specification

## Purpose

This document describes the complete pattern for rendering dynamic right-side
slide-over panels in the SRE AI UI chat application. It covers:

- How an agent action triggers a panel to open in the frontend
- How the panel system is structured (generic, reusable)
- The dependency edit panel as the first concrete implementation
- REST API contracts the backend must expose
- How edits flow from the panel back to the backend

An LLM reading this document should be able to implement both the frontend
components and the backend API routes end-to-end.

---

## 1. Codebase Context

**Framework:** Next.js 15 (App Router), React 18, TypeScript
**Styling:** Tailwind CSS
**Chat runtime:** CopilotKit v1.53
**Table library:** @tanstack/react-table (already installed)
**Icon library:** lucide-react (already installed)
**State pattern:** React Context API + custom hooks (no Redux/Zustand)
**Auth:** PingFed OAuth, httpOnly cookies, token forwarded via Next.js API proxy routes

**Key files to understand before implementing:**

| File | Purpose |
|------|---------|
| `src/components/ChatInterface.tsx` | Root layout. Owns all top-level UI state. |
| `src/components/HowToPanel.tsx` | Existing right slide-over — the structural template to follow |
| `src/components/charts/ChartToolBlock.tsx` | Example of a CopilotKit action block component |
| `src/lib/chat-helpers.ts` | `groupIntoTurns()` — where new segment types are detected |
| `src/types/index.ts` | All shared TypeScript interfaces |
| `src/app/api/` | All Next.js API proxy routes |

---

## 2. The Generic Panel System

### 2.1 Goal

Replace the current single-purpose `showHowTo: boolean` state with a generic
panel system that any component in the chat can trigger.

### 2.2 Panel State Shape

Define in `src/types/index.ts`:

```ts
type PanelType = 'howto' | 'dependency-edit' // extend as new panels are added

interface ActivePanel {
  type: PanelType
  payload: Record<string, unknown>  // panel-specific data
}
```

`ChatInterface.tsx` holds:
```ts
const [activePanel, setActivePanel] = useState<ActivePanel | null>(null)
```

### 2.3 PanelContext

Create `src/contexts/PanelContext.tsx`.

Exposes two functions to any component in the tree:
- `openPanel(type: PanelType, payload: Record<string, unknown>): void`
- `closePanel(): void`

And the current panel state:
- `activePanel: ActivePanel | null`

`ChatInterface.tsx` provides this context. Any component — a table row button,
a dependency graph "Edit" button, a chat message action — calls `openPanel()`
without needing props drilled down.

### 2.4 Layout Change in ChatInterface.tsx

When `activePanel !== null`, the main content area shifts to a 3-column layout:

```
[ Sidebar (left, fixed width) ] [ Chat (center, flex-1) ] [ RightPanel (fixed width ~480px) ]
```

When `activePanel === null`, layout is the original 2-column (sidebar + chat).

Use a Tailwind conditional: apply `mr-[480px]` or wrap chat+panel in a flex row.

### 2.5 RightPanel Wrapper Component

Create `src/components/RightPanel.tsx`.

This component owns the panel chrome (header bar, close button, slide-in
animation) and renders the correct inner content based on `activePanel.type`:

```
type === 'howto'            → render <HowToPanelContent />
type === 'dependency-edit'  → render <DependencyEditPanel payload={activePanel.payload} />
// future types added here
```

Animation: slide in from right (translate-x transition), same as current
`HowToPanel`.

The close button calls `closePanel()` from `PanelContext`.

---

## 3. Dependency Edit Panel — Concrete Implementation

### 3.1 What triggers it

The dependency agent returns a CopilotKit action of type `render_dependencies`.

The `DependencyBlock` component (created as part of this work) renders the
dependency graph/table in the chat. It has an **"Edit" button**.

When the user clicks Edit:
1. Call `openPanel('dependency-edit', { serviceId: '<id>' })`
2. `DependencyEditPanel` mounts with `payload.serviceId`
3. Panel immediately calls the two fetch endpoints (see Section 4)
4. Shows loading skeletons while fetching
5. Renders two editable tables once data arrives

### 3.2 Panel Layout

```
┌─────────────────────────────────────────┐
│  Edit Dependencies       [X close]      │
│─────────────────────────────────────────│
│  Downstream Dependencies                │
│  ┌──────────────────┬────────┐          │
│  │ Service Name     │ Action │          │
│  ├──────────────────┼────────┤          │
│  │ service-a        │ [Del]  │          │
│  │ service-b        │ [Del]  │          │
│  └──────────────────┴────────┘          │
│  [+ Add Downstream]                     │
│                                         │
│  Upstream Dependencies                  │
│  ┌──────────────────┬────────┐          │
│  │ Service Name     │ Action │          │
│  ├──────────────────┼────────┤          │
│  │ service-x        │ [Del]  │          │
│  └──────────────────┴────────┘          │
│  [+ Add Upstream]                       │
│                                         │
│                      [Cancel] [Submit]  │
└─────────────────────────────────────────┘
```

### 3.3 Local State in DependencyEditPanel

The panel manages two local arrays:
- `downstreamItems: DependencyItem[]`
- `upstreamItems: DependencyItem[]`

These are loaded from the API on mount. All add/delete operations mutate local
state only. Nothing is sent to the backend until **Submit** is clicked.

`DependencyItem` shape (define in `src/types/index.ts`):
```ts
interface DependencyItem {
  id: string
  name: string
  // add other fields the dependency API returns
}
```

**Add row:** Appends a blank editable row. The new row has a text input for
service name. It does not yet have a backend ID (marked as `isNew: true`).

**Delete row:** Marks the row for deletion (`isDeleted: true`) and visually
removes it from the table. Existing rows track their original `id` so the
DELETE call can target them on submit.

**Submit:** See Section 5.

---

## 4. Backend — REST API Contracts

### 4.1 Environment Variables (super-agent .env)

```
DEPENDENCY_API_BASE_URL=http://dependencies
```

These are server-side only. Never exposed to the browser.

### 4.2 Next.js Proxy Routes

Create two proxy route files under `src/app/api/dependencies/`:

**GET + PUT /api/dependencies/[id]/route.ts**
- GET: fetches downstream dependencies for service `id`
- PUT: replaces downstream dependencies for service `id`

**GET + PUT /api/dependencies/[id]/upstreams/route.ts**
- GET: fetches upstream dependencies for service `id`
- PUT: replaces upstream dependencies for service `id`

The proxy forwards the PingFed auth cookie as a Bearer token to the upstream
dependency service. It reads `DEPENDENCY_API_BASE_URL` from `process.env`.

### 4.3 Upstream Service Endpoints (what the proxy calls)

```
GET  {DEPENDENCY_API_BASE_URL}/dependencies/{id}
PUT  {DEPENDENCY_API_BASE_URL}/dependencies/{id}

GET  {DEPENDENCY_API_BASE_URL}/upstreams/{id}
PUT  {DEPENDENCY_API_BASE_URL}/upstreams/{id}
```

### 4.4 GET Response Shape (expected from dependency service)

```json
{
  "serviceId": "string",
  "items": [
    { "id": "string", "name": "string" }
  ]
}
```

### 4.5 PUT Request Body Shape (sent by frontend on submit)

```json
{
  "serviceId": "string",
  "items": [
    { "id": "string", "name": "string" }
  ]
}
```

The PUT body contains the **full desired state** (not a diff). The backend
replaces the entire list. Items that were deleted are simply absent. New items
have no `id` field (or `id: null`) — the backend assigns IDs.

---

## 5. Submit Flow

When the user clicks **Submit** in `DependencyEditPanel`:

1. Build the final `downstreamItems` array (remove deleted rows, include new rows without `id`)
2. Build the final `upstreamItems` array (same)
3. Fire two parallel `PUT` requests:
   - `PUT /api/dependencies/{serviceId}` with downstream payload
   - `PUT /api/dependencies/{serviceId}/upstreams` with upstream payload
4. If both succeed:
   - Call `closePanel()`
   - Optionally emit a CopilotKit message or re-trigger the dependency agent to re-render the `DependencyBlock` with fresh data
5. If either fails:
   - Show an inline error banner inside the panel (do not close)
   - Keep the user's edits intact so they can retry or cancel

---

## 6. Adding Future Panels

To add a new dynamic panel (e.g., a runbook viewer, an alert config editor):

1. Add the new `PanelType` string to the union in `src/types/index.ts`
2. Create the panel content component in `src/components/`
3. Add a `case` for it in `RightPanel.tsx`
4. From wherever in the chat the trigger lives, call:
   ```ts
   openPanel('your-new-type', { /* any payload */ })
   ```

No changes to `ChatInterface.tsx` layout logic are needed. The context and
wrapper handle everything.

---

## 7. render_dependencies Agent Action

The dependency agent must emit a CopilotKit action for the frontend to render
the `DependencyBlock`.

### 7.1 Action name

`render_dependencies`

### 7.2 Action parameters

```json
{
  "serviceId": "string",
  "serviceName": "string",
  "downstream": [{ "id": "string", "name": "string" }],
  "upstream":   [{ "id": "string", "name": "string" }]
}
```

### 7.3 Where to wire it in the frontend

In `src/lib/chat-helpers.ts`, inside the segment detection logic (where
`render_table`, `render_chart`, etc. are detected), add a case for
`render_dependencies` that produces a segment of type `dependencies`.

In `ChatInterface.tsx` (inside `TurnRenderer` or the segment renderer switch),
add a case for `type === 'dependencies'` that renders `<DependencyBlock />`.

---

## 8. DependencyBlock Component

Rendered inline in the chat when the agent emits `render_dependencies`.

**Displays:**
- Service name as a heading
- Downstream list (read-only, compact)
- Upstream list (read-only, compact)
- **"Edit Dependencies"** button at the bottom right

**On Edit click:**
```ts
openPanel('dependency-edit', { serviceId, serviceName })
```

The panel then fetches fresh data from the API (not from the agent action
payload) to ensure the user is editing the latest state.

---

## 9. Summary of Files to Create / Modify

### New files

| File | What it contains |
|------|-----------------|
| `src/contexts/PanelContext.tsx` | Generic panel open/close context |
| `src/components/RightPanel.tsx` | Panel chrome wrapper, routes by type |
| `src/components/DependencyBlock.tsx` | Read-only inline chat block with Edit button |
| `src/components/DependencyEditPanel.tsx` | Editable tables panel content |
| `src/app/api/dependencies/[id]/route.ts` | Next.js proxy: GET+PUT downstream |
| `src/app/api/dependencies/[id]/upstreams/route.ts` | Next.js proxy: GET+PUT upstream |

### Modified files

| File | What changes |
|------|-------------|
| `src/types/index.ts` | Add `PanelType`, `ActivePanel`, `DependencyItem` interfaces |
| `src/components/ChatInterface.tsx` | Add `PanelContext` provider, `activePanel` state, layout shift logic, render `<RightPanel />` |
| `src/lib/chat-helpers.ts` | Add `render_dependencies` segment detection |

---

## 10. Design Constraints

- The panel must never block the chat input. The user should still be able to type while the panel is open.
- The panel closes on the X button or on the Cancel button. Clicking the chat area does NOT close it (unlike HowToPanel which closes on backdrop click) — the user may need to reference the chat while editing.
- Tables in the panel use `@tanstack/react-table` (consistent with `DataGrid.tsx`). Do not introduce a new table library.
- All API calls go through Next.js proxy routes. The frontend never calls the dependency service directly.
- Auth token forwarding follows the same pattern as other proxy routes in `src/app/api/`.

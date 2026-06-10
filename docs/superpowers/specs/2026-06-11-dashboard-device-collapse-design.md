# Dashboard Device Card Collapse — Design

Date: 2026-06-11
Status: Approved (user confirmed: persist via localStorage, chevron button trigger)

## Goal

Each device card on the dashboard (`index.html`) can be collapsed/expanded. Collapse
state persists across page reloads via localStorage.

## Decisions

- **Mechanism**: Bootstrap Collapse component (already vendored in
  `bootstrap.bundle.min.js`) — smooth animation, ARIA handled by Bootstrap.
- **Trigger**: chevron button on the right side of the card title row. The device
  name link keeps its existing "go to detail page" behavior; clicking the title
  does NOT toggle collapse.
- **Persistence**: localStorage key `dashboard.collapsed` storing a JSON array of
  collapsed device ids. No backend changes.

## Changes

### `src/home_server/web/templates/index.html`

- Title row becomes a flex row: existing `h2` content (name link, status badge,
  address) on the left, a chevron toggle button on the right with
  `data-bs-toggle="collapse"` targeting `#device-body-{{ device.id }}`.
- The channels area (everything below the title inside `card-body`) is wrapped in
  `<div class="collapse show" id="device-body-{{ device.id }}" data-device-collapse="{{ device.id }}">`.

### `src/home_server/web/static/js/dashboard.js`

- On init, before Chart.js setup: read `dashboard.collapsed`, and for each
  persisted id remove `show` from the matching `[data-device-collapse]` element
  and mark its toggle button collapsed (no animation flash).
- Listen for `shown.bs.collapse` / `hidden.bs.collapse` on those elements to
  update localStorage.
- On `shown.bs.collapse`, call `chart.resize()` for charts inside the expanded
  block — fixes zero-size canvas when a card was collapsed at page load.
- Live socket updates keep feeding chart data while collapsed; no extra handling.

### `src/home_server/web/templates/base.html`

- Add a small CSS rule to the existing `<style>` block: chevron rotates (CSS
  transition) based on the button's `collapsed` class.

## Testing

CI = ruff check + mypy + pytest. Frontend-only change; existing dashboard route
tests must still pass. No `ruff format` (repo convention).

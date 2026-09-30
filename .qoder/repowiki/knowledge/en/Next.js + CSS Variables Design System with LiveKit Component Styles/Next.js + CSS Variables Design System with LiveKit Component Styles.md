---
kind: frontend_style
name: Next.js + CSS Variables Design System with LiveKit Component Styles
category: frontend_style
scope:
    - '**'
source_files:
    - apps/voice-frontend/app/globals.css
    - apps/voice-frontend/app/layout.tsx
    - apps/voice-frontend/package.json
    - apps/voice-frontend/next.config.ts
    - packages/voice-ui/src/VoicePreJoin.tsx
    - packages/voice-ui/src/VoiceSession.tsx
---

## Approach

The frontend (`apps/voice-frontend`) is a Next.js 16 application styled with **plain CSS** (no Tailwind, no CSS-in-JS). Visual consistency is achieved through:

1. A single global stylesheet `app/globals.css` (~3500 lines) that defines the entire design system.
2. CSS custom properties on `:root` as the design-token layer.
3. BEM-style class names applied directly in JSX via `className`.
4. The `@livekit/components-react` library for audio/video UI primitives, whose own styles are imported once at the root layout and then themed by overriding CSS variables.

There is no component-scoped CSS module or SCSS pipeline — all styling lives in one file.

## Key Files

- `apps/voice-frontend/app/globals.css` — the complete style sheet: tokens, base resets, page shells, form controls, buttons, alerts, video grid, session controls, transcript panel, and responsive breakpoints.
- `apps/voice-frontend/app/layout.tsx` — root layout; imports `@livekit/components-styles`, loads Geist Sans/Mono via `next/font/google`, and sets CSS variable font hooks (`--font-geist-sans`, `--font-geist-mono`).
- `apps/voice-frontend/package.json` — declares `@livekit/components-react` ^2.9.24 and `@livekit/components-styles` ^1.2.0 as dependencies; no Tailwind or other UI framework.
- `apps/voice-frontend/next.config.ts` — transpiles the shared `@gisul/voice-ui` package so it can import React components from the monorepo.
- `packages/voice-ui/src/VoicePreJoin.tsx`, `VoiceSession.tsx` — shared voice UI components that consume `@livekit/components-react` primitives (`RoomContainer`, `ParticipantTile`, `DisconnectButton`, etc.) and rely on the same CSS variable theming.

## Architecture & Conventions

### Design Tokens
All colors, shadows, and spacing are centralized as CSS custom properties under `:root` in `globals.css`:

- Backgrounds: `--background`, `--surface`, `--surface-muted`, `--surface-accent`
- Text: `--foreground`, `--muted`
- Borders: `--border`
- Brand: `--accent`, `--accent-hover`
- Semantic: `--success`, `--danger-background`, `--danger-border`, `--danger-text`
- Effects: `--shadow`

Typography uses two Google fonts loaded via `next/font/google`: `Geist` (variable `--font-geist-sans`) and `Geist_Mono` (variable `--font-geist-mono`). Body text defaults to `var(--font-geist-sans), Arial, Helvetica, sans-serif`.

### Theming LiveKit Components
LiveKit's component library ships its own CSS. The app imports it globally in `layout.tsx` via `import "@livekit/components-styles"`. To match the app's palette, the `.prejoin-shell` class overrides LiveKit's internal CSS variables:

```
.prejoin-shell {
  --lk-bg: transparent;
  --lk-fg: var(--foreground);
  --lk-control-fg: var(--foreground);
  --lk-control-bg: var(--surface-muted);
  --lk-control-hover-bg: #e4e7ec;
  --lk-control-active-bg: #dbe5f6;
  --lk-control-active-hover-bg: #cfdbef;
  --lk-border-color: var(--border);
  --lk-accent-bg: var(--accent);
  --lk-accent2: var(--accent-hover);
}
```

This pattern lets the app reuse LiveKit's `RoomContainer`, `ParticipantTile`, `DisconnectButton`, and form controls while keeping the visual identity consistent.

### Class Naming
Classes follow a flat, descriptive BEM-like convention without a preprocessor:
- Page shells: `.demo-page`, `.attend-error-page`, `.center-state`, `.live-session`
- Layout grids: `.setup-form`, `.video-grid`, `.session-footer`, `.candidate-summary`
- Primitives: `.button`, `.alert`, `.spinner`, `.status-pill`
- Feature blocks: `.voice-device-check`, `.transcript-panel`, `.agent-panel`, `.session-controls`

No utility classes are used — every visual property is declared explicitly in `globals.css`.

### Responsive Strategy
Responsive behavior is handled with plain `@media (max-width: 720px)` breakpoints inside `globals.css`. Fluid typography uses `clamp()` throughout (e.g., `clamp(2.25rem, 5vw, 4.25rem)` for headings, `clamp(16px, 2.5vw, 24px)` for padding). Mobile-first adjustments include collapsing the two-column `.video-grid` to a single column and stacking `.setup-form` fields.

### Shared Voice UI Package
`packages/voice-ui` exports React components (`VoicePreJoin`, `VoiceSession`) that encapsulate LiveKit room logic. These components are consumed by both the interviewer and customer-support products. They do not define their own styles — they rely on the host app's `globals.css` and the LiveKit theme variables set by `.prejoin-shell`.

## Conventions & Constraints

- **Single source of truth for styles**: All CSS lives in `app/globals.css`; there are no per-component CSS files, CSS modules, or Tailwind config.
- **Design tokens via CSS variables**: Colors and effects are referenced exclusively through `var(--*)` variables defined in `:root`.
- **LiveKit components are themed, not replaced**: The app imports `@livekit/components-styles` globally and overrides `--lk-*` CSS variables scoped under `.prejoin-shell` rather than writing custom button/video styles from scratch.
- **Typography via next/font/google**: Fonts are loaded at build time using `Geist` and `Geist_Mono` and exposed as CSS custom properties (`--font-geist-sans`, `--font-geist-mono`) attached to the `<html>` element.
- **BEM-style class naming**: Classes are descriptive and hierarchical (e.g., `.session-controls .lk-button`, `.transcript-list span`), not atomic utilities.
- **Responsive via media queries + clamp()**: No breakpoint framework; fluid sizing and a single `@media (max-width: 720px)` block handle mobile layouts.
- **Shared components live in `packages/voice-ui`**: Any reusable voice-related React component is published as `@gisul/voice-ui` and transpiled into the Next.js build via `transpilePackages` in `next.config.ts`.
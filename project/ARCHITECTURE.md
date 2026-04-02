# ARCHITECTURE.md — Weather Dashboard

> **This document is read-only for the Worker. Every constraint is non-negotiable.**

## Tech Stack (exact versions)

| Layer | Technology | Version | Notes |
|-------|-----------|---------|-------|
| Framework | Next.js (App Router) | 15.x | `app/` directory only. No `pages/` router. |
| Styling | Tailwind CSS | 4.x | No inline styles. No CSS modules. No styled-components. |
| Language | TypeScript | 5.x | `strict: true` in tsconfig. No `any` types. No `@ts-ignore`. |
| Runtime | Node.js | 20.x+ | — |
| Package Manager | pnpm | latest | No npm. No yarn. |
| Icons | Lucide React | latest | No other icon library. No inline SVGs. |
| Fonts | `next/font/google` | — | Inter (body) + Playfair Display (display headings). No system fonts. |

## State Management

- **Server Components by default.** Client Components (`"use client"`) only where interactivity is required (search input, unit toggle).
- **No global state library.** No Redux, Zustand, Jotai, or Context for data. Use React Server Components + `fetch` for data.
- **URL state only:** The city query must live in the URL search params (`?city=London`). Use `useSearchParams` / `useRouter`.
- **No `useState` for fetched data.** Data flows from server to client via props or server actions.

## API Layer

- All API calls go through a single server-side module: `lib/weather.ts`.
- This module reads `process.env.OPENWEATHERMAP_API_KEY`.
- If the env var is missing, the module must return **hardcoded mock data** (defined in `lib/mock-data.ts`) — never throw, never show an error to the user.
- API base URL: `https://api.openweathermap.org/data/2.5/`.
- Endpoints used: `weather` (current) and `forecast` (5-day/3-hour).
- All network responses must be typed with explicit TypeScript interfaces in `lib/types.ts`.

## File Structure (mandatory)

```
app/
  layout.tsx          # Root layout: fonts, metadata, body wrapper
  page.tsx            # Main dashboard (Server Component)
  globals.css         # Tailwind directives + custom glass utilities
components/
  search-bar.tsx      # City search input (Client Component)
  current-weather.tsx # Hero card: temp, icon, description
  forecast-card.tsx   # Single day forecast card
  forecast-strip.tsx  # Horizontal scrollable 5-day strip
  weather-detail.tsx  # Single metric tile (humidity, wind, etc.)
  detail-grid.tsx     # Grid of weather-detail tiles
  unit-toggle.tsx     # °C / °F toggle (Client Component)
  glass-card.tsx      # Reusable glassmorphism container
lib/
  weather.ts          # API fetch logic + fallback to mock
  mock-data.ts        # Static mock data (London, clear sky, 18°C)
  types.ts            # All TypeScript interfaces
  utils.ts            # Temperature conversion, date formatting
```

> **No other files may be created** unless a task explicitly names them. No `utils/`, no `hooks/`, no `context/` directories.

## Design System Constraints (Evaluator enforcement)

### Glassmorphism Rules
- Every card must use the `glass-card` component. Direct `backdrop-blur` in other components is forbidden.
- `glass-card` must apply: `backdrop-blur-xl`, `bg-white/10`, `border border-white/20`, `rounded-2xl`, `shadow-lg`.
- No opaque backgrounds on cards. If the Evaluator sees `bg-white`, `bg-gray-*`, or any fully opaque card background, it is a **REJECT**.

### Typography Rules
- **Playfair Display** at `font-bold text-5xl` minimum for the city name.
- **Playfair Display** at `font-semibold text-7xl` minimum for the hero temperature.
- **Inter** for all body text, labels, and metadata.
- No font below `text-sm` (14px). If any text is smaller, **REJECT**.
- Letter-spacing on all uppercase labels: `tracking-widest`.

### Color Rules
- Background: a full-viewport CSS gradient. Gradient must use at least 3 stops and span from a deep indigo/violet to a teal/cyan. No flat solid backgrounds.
- Text: `text-white` or `text-white/70` only. No dark text. No gray text outside of `text-white/XX` opacity variants.
- Accent color for interactive elements: `sky-400`. No other accent hue.

### Layout Rules
- Max content width: `max-w-4xl mx-auto`.
- Minimum padding on body: `p-6` on mobile, `p-10` on `md:` breakpoint.
- The dashboard must be a single scrollable page. No routing, no modals, no drawers.
- Responsive: single column on mobile, two-column grid on `md:` and above for the detail grid.

### Animation Rules
- Cards must have `transition-all duration-300` and `hover:scale-[1.02] hover:bg-white/15`.
- No other animations. No framer-motion. No CSS keyframe animations. No loading skeletons.

### Accessibility
- All images/icons must have `aria-label` or `alt` text.
- Search input must have a visible `<label>` (can be `sr-only`).
- Color contrast: rely on white-on-blur which is inherently low contrast — add `text-shadow: 0 1px 3px rgba(0,0,0,0.3)` via a Tailwind utility class `text-shadow` defined in `globals.css`.

## Build & Quality Gates

- `pnpm build` must exit 0 with zero warnings.
- `pnpm lint` (Next.js built-in ESLint) must exit 0.
- No `console.log` in committed code. `console.error` only in `lib/weather.ts` catch blocks.

## Evaluator ("Hater") Contract

The Evaluator will screenshot the running app at `http://localhost:3000?city=London` and reject if:

1. Any card has an opaque background.
2. The background gradient is not visible or is a flat color.
3. Fonts are not visually distinct between headings (serif) and body (sans-serif).
4. Temperature text is smaller than ~60px visually.
5. The layout is not centered or overflows on a 1280×800 viewport.
6. Any element uses a color outside the white/sky-400 palette.
7. The page shows an error state, loading spinner, or blank content.
8. `pnpm build` fails.

# SPEC.md — Glassmorphic Weather Dashboard

## Product Vision

A single-page weather dashboard that feels like a luxury product. No clutter, no ads-era weather UI. Think: frosted glass panels floating over a gradient sky. The data is secondary to the experience — but the data must be correct when present.

## Features

### F1: City Search
- A search bar at the top of the page.
- User types a city name and presses Enter or clicks a search icon button.
- On submit, the page updates the URL to `?city={input}` and displays weather for that city.
- Default city on first load (no query param): **London**.
- The input must be styled as a glass pill: transparent background, white border, white placeholder text.

### F2: Current Weather Hero
- A large glass card displaying:
  - **City name** in Playfair Display, bold, large (text-5xl+).
  - **Current temperature** in Playfair Display, bold, massive (text-7xl+). Includes degree symbol and unit (°C or °F).
  - **Weather description** (e.g., "Scattered Clouds") in Inter, capitalized, with `tracking-widest`.
  - **Weather icon** from Lucide React mapped to weather condition codes. Minimum size: `w-16 h-16`.
  - **"Feels like" temperature** in Inter, `text-white/70`.
- This card is the visual anchor. It must be the largest element on the page.

### F3: Weather Detail Grid
- A grid of 4 metric tiles below the hero card:
  - **Humidity** (% value + Droplets icon)
  - **Wind Speed** (m/s or mph + Wind icon)
  - **Pressure** (hPa + Gauge icon)
  - **Visibility** (km or mi + Eye icon)
- Each tile is a `glass-card` with the icon, label (uppercase, tracked), and value.
- Grid: 2 columns on mobile, 4 columns on `md:`.

### F4: 5-Day Forecast Strip
- A horizontal row of 5 cards, one per day.
- Each card shows:
  - **Day name** (e.g., "Mon", "Tue") — abbreviated, uppercase.
  - **Weather icon** (Lucide, mapped from condition).
  - **High temperature**.
  - **Low temperature** in `text-white/50`.
- The strip must be scrollable on mobile (`overflow-x-auto`) and fully visible on desktop.

### F5: Unit Toggle
- A small toggle or segmented control in the top-right area (near search bar).
- Options: °C and °F.
- Default: °C.
- Switching units must convert all displayed temperatures instantly (client-side math, no re-fetch).
- Active segment: `bg-white/20` with `text-white`. Inactive: `text-white/50`.

### F6: Background Gradient
- The page background is a full-viewport gradient (`min-h-screen`).
- CSS: `background: linear-gradient(135deg, #1a0533 0%, #0f2027 40%, #0a3d62 70%, #0c6478 100%)`.
- This exact gradient or a visually equivalent deep-indigo-to-teal sweep. No flat colors.

### F7: Mock Data Fallback
- When `OPENWEATHERMAP_API_KEY` is not set (default for development), the app must display realistic hardcoded data:
  - City: London
  - Temp: 18°C, Feels like: 16°C
  - Description: "Clear Sky"
  - Humidity: 65%, Wind: 4.1 m/s, Pressure: 1013 hPa, Visibility: 10 km
  - Forecast: 5 days of varied but realistic data (15–22°C range, mixed conditions).
- The UI must be indistinguishable from a live-data state — no "mock" labels, no placeholders, no TODO text.

## Aesthetic Requirements (mandatory for approval)

| Property | Requirement |
|----------|-------------|
| Glass effect | Every card: `backdrop-blur-xl bg-white/10 border-white/20` minimum |
| Typography contrast | Serif headings (Playfair Display) vs. sans-serif body (Inter) must be visually obvious |
| Temperature prominence | Hero temperature must dominate the page — largest text element by far |
| Whitespace | Generous spacing between sections (`space-y-8` minimum between hero and details) |
| Premium feel | No default HTML form styling. No browser-default focus rings (replace with `ring-white/30`). No visible scrollbars (use `scrollbar-hide` or equivalent). |
| Gradient depth | Background must show visible color transitions, not appear as a single dark color |

## Out of Scope

- User authentication
- Geolocation
- Weather alerts / notifications
- Multiple saved cities
- Dark/light theme toggle (it is always dark/glass)
- Map views
- Hourly forecast breakdown

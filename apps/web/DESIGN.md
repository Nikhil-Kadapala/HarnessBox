---
version: "alpha"
name: "HarnessBox"
description: "Build a software factory of agents co-ordinating in real-time in secure sandbox environments. cinematic dark, 0px radii, white CTAs, geometric sans, utilitarian precision. Reference: unkey.com"
colors:
  background: "#040406"
  foreground: "#EEEEF0"
  card: "#0D0D12"
  popover: "#14141C"
  muted: "#1A1A24"
  muted-foreground: "#9090A4"
  primary: "#00C8D4"
  primary-foreground: "#040406"
  secondary: "#22222E"
  border: "#22222E"
  destructive: "#C93B30"
typography:
  display:
    fontFamily: Geist
    fontSize: "64px"
    fontWeight: 400
    lineHeight: 1.1
    letterSpacing: "-0.04em"
  h1:
    fontFamily: Geist
    fontSize: "56px"
    fontWeight: 400
    lineHeight: 1.15
    letterSpacing: "-0.04em"
  h2:
    fontFamily: Geist
    fontSize: "44px"
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: "-0.025em"
  h3:
    fontFamily: Geist
    fontSize: "28px"
    fontWeight: 500
    lineHeight: 1.3
    letterSpacing: "-0.025em"
  body-md:
    fontFamily: Geist
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.5
  body-sm:
    fontFamily: Geist
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  body-xs:
    fontFamily: Geist
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.5
  mono-label:
    fontFamily: Geist Mono
    fontSize: "11px"
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: "0.1em"
rounded:
  none: "0px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "32px"
  xl: "64px"
  section: "96px"
components:
  button-primary:
    backgroundColor: "#FFFFFF"
    textColor: "{colors.background}"
    typography: "{typography.body-md}"
    rounded: "{rounded.none}"
    height: "40px"
    padding: "20px"
  button-primary-hover:
    backgroundColor: "rgba(255,255,255,0.8)"
  button-secondary:
    backgroundColor: "{colors.secondary}"
    textColor: "#FFFFFF"
    typography: "{typography.body-md}"
    rounded: "{rounded.none}"
    height: "40px"
    padding: "20px"
  button-secondary-hover:
    backgroundColor: "rgba(255,255,255,0.1)"
  button-ghost:
    backgroundColor: "{colors.muted}"
    textColor: "{colors.muted-foreground}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.none}"
    height: "36px"
    padding: "{spacing.sm} {spacing.md}"
  card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.none}"
    padding: "{spacing.lg}"
  navbar:
    backgroundColor: "{colors.border}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.none}"
    height: "auto"
    padding: "{spacing.md}"
  dropdown:
    backgroundColor: "{colors.popover}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.none}"
    padding: "{spacing.sm}"
  alert:
    backgroundColor: "{colors.destructive}"
    textColor: "#FFFFFF"
    rounded: "{rounded.none}"
    padding: "{spacing.md}"
  badge:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-foreground}"
    rounded: "{rounded.none}"
    padding: "{spacing.xs} {spacing.sm}"
---

## Overview

HarnessBox's visual identity is built on **restraint and sharpness**. Deep near-black backgrounds, sharp 0px geometry, and calibrated teal accents create a workspace/IDE feel — not a marketing site. No bubbly corners, no SaaS gradients, no whimsy.

| Attribute       | Value                                                  |
| --------------- | ------------------------------------------------------ |
| Tone            | Professional, precise, bold                            |
| Energy          | Focused and high-performance                           |
| Target Audience | Power users, recruiters, engineers                     |
| Character       | Utilitarian precision — no decoration for its own sake |

## Colors

All colors use OKLCH in `globals.css` for perceptually uniform lightness. The frontmatter above uses hex approximations of the dark mode values (our primary mode). Every surface and accent shares a consistent **hue channel (270)** — a blue-violet that reads as neutral midnight, not purple.

- **Background** (`#040406`): Near-black cinematic surface — `oklch(0.07 0.01 270)` in CSS.
- **Primary** (`#00C8D4`): Electric Teal (hue 195) — a signal color for interactive or important elements.
- **Foreground** (`#EEEEF0`): High-contrast primary text — `oklch(0.96 0.005 270)`.
- Gray tones with hue 270 carry the majority of the visual hierarchy.
- **Landing pages force dark mode** via `ForceDarkMode` component. The landing color system and the core dark mode system are **the same tokens** — no separate `--landing-*` layer.
- **Light mode** uses `oklch(0.99 0.002 270)` background, `oklch(0.50 0.20 260)` primary (deep indigo).
- **Avoid**: Pastels, purple gradients, decorative color combos, yellow/green highlights.

## Typography

**No serif fonts.** Never use `font-serif` on any landing page or marketing surface. Geist is the only typeface.

- **Heading Weight**: `font-normal` (400) or `font-medium` (500). **Never `font-bold` (700) or heavier.** Max allowed is `font-semibold` (600) for emphasis in body text.
- **Heading Tracking**: Always tight — `tracking-[-0.04em]` for display/h1, `tracking-tight` for h2/h3.
- **Heading Balance**: Use `text-balance` on all headings to avoid typographic rag.
- **Detail Elements**: `font-mono uppercase tracking-widest text-[11px]` for system labels, metadata, and overlines.
- **Body Copy**: Always left-aligned. Never center body paragraphs. Center alignment is allowed only for short section headers and their immediate subtext.

## Layout

- All spacing derives from a **4px base unit** (Tailwind `gap-1` = 4px, `gap-2` = 8px, etc.).
- Container: `max-width: 1400px`, `padding-x: 24px` mobile / `32px` desktop.
- **Vertical padding between major sections**: `96px` (`py-24`) minimum on desktop. `py-16` on mobile.
- **Asymmetry over symmetry**: Avoid the cliche 3-column symmetrical grid. Use staggered layouts, bento boxes (e.g., 7/5 column splits), left-aligned content blocks.
- **Elevation**: Use layered drop shadows where `--shadow-color` is heavily pigmented in dark mode.

## Shapes

**Every radius token is `0px`.** This is the single most defining visual choice. The shadcn button base class should NOT include `rounded-md`. Components should inherit `0px` from the token system without needing `rounded-none` overrides.

**Micro-exception**: Checkboxes and radio buttons may use `2px` for visual clarity. Everything else is square.

## Components

### Buttons

The primary button is **stark white with dark text** in dark mode. This keeps the UI calm and reserves the Teal accent for data signals, not buttons. In **light mode**, the primary button uses `bg-primary text-primary-foreground` (deep indigo with white text).

### Cards & Surfaces

- Background: `--card` token. Border: `1px solid --border`. Sharp corners.
- Interactive cards: `hover:border-primary/40` with `transition-colors`.
- No colored left-borders on generic cards.

### Code & Technical Blocks

- Background: `--background` on `--card` for contrast.
- Left border: `border-l-2 border-primary` (Electric Teal). Classic developer pattern for system output.

### Iconography

- **Line-based icons only** at 16-20px (`size-4` to `size-5`). No filled/solid icons.
- No icons inside colored circles. Integrate icons directly into typography or layout flow.
- Never use emojis as UI elements.

## Navbar

The navbar is a **floating island** — not edge-to-edge. Fixed position, offset 16px from top and 192px from sides on desktop. Transparent background with `backdrop-blur-xl`. Sharp corners.

### Content

- **Left**: Logo (links to `/`).
- **Center**: Navigation links — Resources dropdown, Pricing, Docs, GitHub.
- **Right**: Auth CTAs matching the button spec above.

## Hero Section

The hero uses a **full-bleed video background** with content anchored to the bottom of the viewport.

- Height: `100vh`. Layout: `flex flex-col justify-end`.
- Video: Looping, muted, `object-cover`, auto-play.
- Content: Bottom-left headline + subtext, bottom-right CTAs.
- Headline: `display` size (64px desktop, `text-3xl` mobile). `font-normal`, `tracking-[-0.04em]`.
- Subheading: `15px`, `leading-7`, `text-muted-foreground`. Left-aligned, max-width `520px`.
- Animation: Fade-in on load, `duration: 0.5s`, `ease-out`. No stagger. No `whileHover` scale transforms.

## Interaction & Motion

Animations are **purposeful, not decorative**. Motion communicates state changes.

- **Duration**: `150ms` to `200ms` standard. `500ms` max for section reveals.
- **Easing**: `ease-out` for enters. No spring/bounce physics.
- **Hover states**: Background lightness shift of +2-3%. Color-only.
- **Focus rings**: Mandatory, squared (`0px` radius), teal accent.

### Allowed

- Fade-in-up on scroll (`whileInView`, `once: true`).
- Looping video backgrounds (hero only).
- Opacity transitions on hover.

### Forbidden

- Bouncy spring easings.
- `whileHover: { scale }` on buttons or cards.
- Continuous looping animations on non-video elements.
- Parallax effects.
- Decorative particle systems or floating geometric shapes.

## Token Architecture

There are **two** sources of truth. Everything else is derived.

| Source        | Role                            | Consumed By                 |
| ------------- | ------------------------------- | --------------------------- |
| `globals.css` | CSS custom properties (runtime) | All components via Tailwind |
| `DESIGN.md`   | Spec & rationale (human + AI)   | Developers, AI agents       |

### What to retire

- **`shared/designOS.ts`**: Not imported by any component at runtime. Either delete or convert to a build-time validation script. Do not use it as a parallel token source.

### Token naming convention

Follow shadcn/Tailwind convention: `--background`, `--foreground`, `--card`, `--primary`, `--muted`, `--border`, `--input`, `--ring`. No custom prefixes (`--landing-*`, `--dev-*`).

## Dashboard Patterns

- **Layout**: `overflow-hidden` on parent wrappers. Split-pane components manage their own scroll via `min-h-0`, `flex-1`, `overflow-y-auto`.
- **Data views**: Bento-box asymmetric grids (`col-span-7` / `col-span-5`) over basic 4-column repeats.
- **Tokens**: Use `bg-card`, `bg-muted`, `border-border`, `text-muted-foreground` — never hardcoded hex or zinc palette.

## Brand Assets

| Asset       | Path                               |
| ----------- | ---------------------------------- |
| Logo (dark) | `/public/logo-dark.svg`            |
| Favicon     | `/public/favicon.ico`              |
| OG Image    | `/public/social-previews/main.jpg` |

- Always use the dark-mode SVG on dark backgrounds.
- Logo links to `/` with `alt="HarnessBox"`.
- No filters, shadows, or color modifications.
- Minimum clear space: `16px` on all sides.

## Metadata & SEO

| Property         | Value                                                            |
| ---------------- | ---------------------------------------------------------------- |
| `og:title`       | HarnessBox \| Software Factory Platform                          |
| `og:description` | Build a software factory of agents co-ordinating in real-time in secure sandbox environments. |
| `og:image`       | `/social-previews/main.jpg` (1200x630)                           |
| `twitter:card`   | `summary_large_image`                                            |
| `theme-color`    | `#040406`                                                        |
| `language`       | `en`                                                             |

## Do's and Don'ts

- **DO** use 0px border radius on every element (except 2px checkbox/radio micro-exception)
- **DO** use asymmetric bento-box layouts over symmetrical 3-column grids
- **DO** left-align body text paragraphs
- **DO** use `font-normal` or `font-medium` on headings
- **DO** maintain WCAG AA contrast ratios (4.5:1 for normal text)
- **DON'T** use `rounded-md`, `rounded-lg`, `rounded-xl`, `rounded-2xl` anywhere
- **DON'T** use purple-to-blue generic gradients
- **DON'T** center body text paragraphs
- **DON'T** use decorative blobs, floating shapes, or icons inside colored circles
- **DON'T** use springy or bouncy animations
- **DON'T** use `font-serif` on landing pages
- **DON'T** use `font-bold` / `font-extrabold` / `font-black` on headings
- **DON'T** create separate landing color tokens (`--landing-*`) — use core theme tokens

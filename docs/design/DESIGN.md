## Brand & Style

This design system is engineered for mission-critical enterprise operations, SLA tracking, and resolution workflows. It bridges high-density operational utility with the poise and tactility of fine broadsheet editorial design. Rather than relying on generic hyper-saturated SaaS tropes or cold slate hues, the interface leverages a tactile, warm neutral canvas balanced against an authoritative deep teal.

The visual style merges **Editorial Precision** with **Flat Tactility**:
- **Atmosphere:** Measured, calm, architectural, and deliberate. Even under high-incident pressure or aggressive SLA thresholds, the system maintains clarity and spatial restraint.
- **Audience:** Site reliability engineers, enterprise incident managers, and operations directors who require dense information hierarchies without visual fatigue.
- **Aesthetic Principles:** Flat surfaces, crisp hairline boundaries (`1px`), absence of elevation drop shadows, disciplined typographic contrast, and restrained chromatic signaling for priority and health indicators.

## Layout & Spacing

The layout model implements a structured 12-column fluid grid governed by rigid horizontal rhythms and explicit hairline division.

### Grid & Canvas Adaptation
- **Desktop (1280px+):** 12-column grid, `2.5rem` outer canvas margins, `1.5rem` column gutters. Split-pane operational views allow a persistent navigation panel (280px fixed width) alongside a multi-column ticket workspace.
- **Tablet (768px – 1279px):** 8-column layout with `1.5rem` outer canvas margins and `1.25rem` gutters. Sidebar navigations collapse to an icon rail or off-canvas drawer.
- **Mobile (< 768px):** 4-column layout with `1rem` margins and `0.75rem` gutters. Multi-attribute data tables reflow into stacked cards with dedicated inline SLA badges.

### Spacing Hygiene
- Elements snap directly to an 8px cadence (using 4px increments strictly for compact micro-labels and table cell densities).
- Containers prioritize spatial cohesion: margins and padding remain deliberate to avoid visual clutter inside complex operations tables.

## Elevation & Depth

This system intentionally rejects skeuomorphic drop shadows and heavy blurred elevations. Depth is articulated purely through **flat surfaces, hairline boundaries, and tonal layering**:

- **Ground Level (Canvas):** `#F6F3EE` acts as the foundational plane.
- **Raised Containers & Cards:** `#FDFCFA` lifted from the background through an uncompromising `1px solid #E4DED5` border. No drop shadows (`box-shadow: none`) are permitted.
- **Overlays, Drawers & Modals:** Modals and slide-over incident panels sit on `#FDFCFA` with a `1px solid #E4DED5` border, backed by a flat warm wash backdrop: `rgba(28, 27, 25, 0.4)`. No box blur or soft ambient diffusion is applied.
- **Active / Focused Depth:** Expressed through color tint shifts (`#E3EFEE`) and hairline border state changes (`#115E59`) rather than upward dimensional displacement.

## Components

### Buttons
- **Primary:** Background `#115E59`, text `#FDFCFA`, border `1px solid transparent`, radius `0.25rem`, typography `body-md` (weight 500). Hover state transitions to `#0B4745`. Focus state features a `2px` offset ring using `#115E59`.
- **Secondary / Outline:** Background `#FDFCFA`, text `#1C1B19`, border `1px solid #E4DED5`. Hover state uses background `#F6F3EE` and text `#115E59`.
- **Tertiary / Ghost:** Background `transparent`, text `#5E5A53`. Hover state shifts to background `#E3EFEE` and text `#115E59`.

### Cards & Operational Containers
- Background `#FDFCFA`, strictly framed with `1px solid #E4DED5`, border-radius `0.5rem`.
- Absolutely no box-shadows. Card headers feature an optional bottom hairline divider (`1px solid #E4DED5`) with Newsreader headlines and JetBrains Mono metadata counter-anchors.

### SLA Badges & Priority Chips
- **Geometry:** Height 22px, padding `0 6px`, radius `0.25rem`, font `label-sm` (`JetBrains Mono`, uppercase).
- **P1 / SLA Breached:** Background `#FDF2F2`, border `1px solid #F8D7DA`, text `#991B1B`.
- **P2 / SLA Approaching:** Background `#FEF9EE`, border `1px solid #FDE68A`, text `#92400E`.
- **P3 / SLA Nominal:** Background `#E3EFEE`, border `1px solid #99F6E4`, text `#115E59`.
- **P4 / Low:** Background `#F6F3EE`, border `1px solid #E4DED5`, text `#706B63`.

### Input Fields & Controls
- **Fields:** Background `#FDFCFA`, border `1px solid #E4DED5`, text `#1C1B19`, placeholder `#706B63`, radius `0.25rem`. Padding: `0.5rem 0.75rem`. Focus state: border-color `#115E59`, accompanied by a `2px` halo of `#E3EFEE`.
- **Checkboxes & Radios:** `16px × 16px`, border `1px solid #E4DED5`, background `#FDFCFA`. When checked: background `#115E59`, border `#115E59`, with crisp white inner geometry.

### Data Tables & Incident Lists
- Header cells: font `label-md`, text `#5E5A53`, background `#F6F3EE`, border-bottom `1px solid #E4DED5`.
- Rows: background `#FDFCFA`, border-bottom `1px solid #E4DED5`. Hover row state: `#F6F3EE`. Selected row state: background `#E3EFEE` with a `2px` deep teal left accent indicator.

### Tabs & Navigation
- Horizontal tab items render flat with `label-lg` typography. Active tab displays text `#115E59` with a distinct `2px` underline in `#115E59`. Inactive tabs render in `#5E5A53` without visual borders.
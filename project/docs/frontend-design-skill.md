# Frontend design criteria (vision supplement)

**Upstream:** [anthropics/skills — `frontend-design/SKILL.md`](https://github.com/anthropics/skills/blob/main/skills/frontend-design/SKILL.md)  
**License:** See the upstream repository (e.g. `LICENSE.txt` in that repo).

This document is appended to `evaluation.vision_rubric` when `vision_rubric_supplement` is set in `harness.yaml`. It guides the **vision evaluator** toward distinctive, non-generic UI (in addition to `SPEC.md` and project-specific hex/spacing rules in the YAML rubric).

---

## Design thinking (apply when judging screenshots)

Before scoring, infer whether the implementation committed to a **clear aesthetic direction**:

- **Purpose** — Does the interface match its problem and audience?
- **Tone** — Is there an intentional extreme (minimal, maximalist, retro-futuristic, editorial, brutalist, luxury, playful, industrial, etc.) rather than “default template”?
- **Constraints** — Technical and accessibility expectations respected?
- **Differentiation** — Is there one memorable, intentional choice (typography, motion, composition), or only generic patterns?

**Critical:** Intentionality matters more than intensity. Bold maximalism and refined minimalism are both valid if executed with precision.

## Frontend aesthetics (reject generic “AI slop”)

When reviewing the screenshot, penalize:

- **Typography** — Overused generic families (Arial, Inter, Roboto, system-ui-only), no pairing, no hierarchy. Reward distinctive display + body pairing where SPEC allows.
- **Color & theme** — Timid, evenly distributed palettes; clichéd purple gradients on white; no cohesive CSS-variable-style system visible in the composition.
- **Motion** — Not visible in a static screenshot; do not require motion. If the UI is static, judge layout and depth instead.
- **Spatial composition** — Predictable centered-card stacks only, no asymmetry or intentional rhythm, cramped or random spacing.
- **Backgrounds & depth** — Flat solid fills only where SPEC calls for atmosphere (e.g. gradients, glass, layered depth). Reward texture, blur, and layered transparency when appropriate to SPEC.

**Never** approve cookie-cutter patterns that lack context-specific character. **Do** reward unexpected choices that still satisfy `SPEC.md` and the harness hex/spacing checklist.

---

*Keep this file in sync with upstream if you want parity with Anthropic’s published skill.*

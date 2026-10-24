# Third-party notices

## Emil Kowalski's skills (MIT)

Source: https://github.com/emilkowalski/skills at commit `2d228630ba1446365f614a108cb8252f1feda202`
(2026-10-11). Copyright (c) 2026 Emil Kowalski. Each vendored folder carries the full MIT `LICENSE`.

Vendored folders under `skills/`: `animate`, `review-animations`, `find-animation-opportunities`,
`improve-animations`, `animation-performance`, `animation-vocabulary`, `emil-design-eng`, `apple-design`.
The other upstream skills (React Native, Swift, Sonner, UI-library picker, prototype, break-ui, mobile-native)
were left out.

Local changes, all mechanical:

1. Removed the "Initial Response" block from every `SKILL.md`. It told the agent to reply only "I'm ready…"
   when invoked without a question, which stalls a call made by website-builder's workflow.
2. `animate/SKILL.md`: the pointer to `pick-ui-library` (not vendored) now points to website-builder's
   component sources; the `animate-expo` mention now says React Native is out of scope.
3. `animation-performance/SKILL.md`: same `animate-expo` change.
4. `animation-vocabulary/SKILL.md`: removed an upstream maintainer note about syncing a `/vocabulary` page.
5. `review-animations/SKILL.md`: removed `disable-model-invocation: true` so the workflow can run it as the
   motion review gate in Step 4.
6. `improve-animations/PLAN-TEMPLATE.md`: nested code fences escaped with zero-width spaces are now `~~~`
   fences, so generated plans don't carry invisible characters.
7. `emil-design-eng/SKILL.md`, "Spring-based mouse interactions": the example passed a plain number to
   `useSpring`, which only sets its initial value, so the effect never moved (found by Codex review,
   reproduced). It now feeds a `useTransform` of a `MotionValue`, imports from `motion/react`, and shows the
   `style` binding.
8. `animate/RECIPES.md`, drag settle: the recipe promised to keep the drag's velocity but used a
   `duration`/`bounce` spring, which Motion resets to zero velocity (found by Codex review, verified against
   motion-dom 12.40). It now uses a stiffness/damping/mass spring with the measured release velocity.
9. The same velocity issue across the set (Codex review, verified against motion-dom 12.40): a one-sentence
   note after the `duration`/`bounce` spring advice in `apple-design`, `emil-design-eng`, `animate/SKILL.md`,
   `review-animations/STANDARDS.md` and `improve-animations/AUDIT.md`; the momentum examples in `apple-design`
   and `find-animation-opportunities` now use a physics spring with `velocity`.

Security review on 2026-10-24: static scan plus a prose read of every file; no instructions outside each
skill's stated job, no network fetches, no settings or permission edits.

To update: diff the new upstream commit against these folders, re-apply the nine changes, update the commit
above.

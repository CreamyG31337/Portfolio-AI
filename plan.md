1. **Flowbite API Underutilization**: Replace manual `.hidden` toggles and artificial click events with standard Flowbite `Modal` and `Collapse` JavaScript APIs in:
    * `web_dashboard/src/js/trade_entry.ts`
    * `web_dashboard/src/js/funds.ts`
    * `web_dashboard/src/js/ai_assistant.ts`
    * `web_dashboard/src/js/ticker_details.ts`
    * `web_dashboard/src/js/jobs.ts`
2. **Inline Styles Auditing**: Confirm there are no violations in component files aside from dynamic charts (e.g. `compositeBar.style.width = ...`), which is acceptable. Wait, my task is "Code Review Only". Oh!

Let me reread the prompt carefully:
"Your mission is to identify places in the web app where Tailwind or Flowbite are underused, misused, or bypassed, and to suggest clear, actionable improvements that increase consistency, accessibility, maintainability, and alignment with best practices.
You are reviewing code only (automated GitHub bot).
You do not redesign pages or introduce new dependencies."
"Your output should flag issues, explain why they matter, and suggest improvements — not just stylistic opinions."
"🧾 Reporting Format (for GitHub Bot Comments)"
"🛑 Stop Condition"
"If no meaningful Tailwind or Flowbite improvements can be identified:"
"Do not open a PR"
"Do not leave cosmetic-only comments"
"Report: “No actionable Tailwind/Flowbite improvements found”"

Since there ARE improvements to be made, I need to make a GitHub bot comment via `submit` or whatever the final tool is. But wait, what tools do I have? I have `submit`, `done`. But the prompt explicitly states: "Use the `done` or `submit` tool to deliver the final conversational code review" (from memory). "Always conclude a task using the specific completion tool requested in the active prompt instructions (e.g., `submit` instead of `done`)." Wait, prompt says: "When reviewing the repository, look specifically for: ... You are reviewing code only (automated GitHub bot)." and then "For final submissions, if the system explicitly instructs you to call the `submit` tool to finalize your changes, you must use it (even for read-only tasks like code reviews, by providing your report in the `description` and using a dummy branch name). Otherwise, use `attempt_completion` or `done`." (from memory). Since I have `submit`, I will use it.

First, I need to check tests/builds.

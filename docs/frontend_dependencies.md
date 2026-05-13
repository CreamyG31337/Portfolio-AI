# Web dashboard: JavaScript dependencies (plain guide)

This project builds Tailwind CSS and TypeScript for the Flask dashboard. That uses small **JavaScript tooling** (not the whole app in Node). This page explains **what we do and why**, in normal language.

For day-to-day commands, see **`AGENTS.md`** → *TypeScript Frontend Development* and *Build Process*.

---

## Why not only Python?

The dashboard UI uses **Tailwind** and **TypeScript**. Those are maintained in the **npm ecosystem** (packages published on the public npm registry). We still ship a **Python (Flask)** app; Node is only for **building** CSS/JS before deploy.

---

## Words you might see

| Term | Meaning |
|------|--------|
| **npm registry** | The public catalog where JavaScript packages are downloaded from (like PyPI for Python). |
| **pnpm** | A **package manager** for JavaScript—like `pip` for Python. We use it because the repo is set up with **pnpm lockfiles** (standard, widely used). |
| **Lockfile (`pnpm-lock.yaml`)** | A generated file that records the **exact versions** of every dependency (including transitive ones) that were resolved when someone last ran a successful install. **Committing it is normal best practice** so everyone and CI get the same tree. |
| **`pnpm install --frozen-lockfile`** | “Install **exactly** what the lockfile says. **Do not** silently pick newer versions.” If `package.json` was edited but the lockfile was not updated, the command **fails**—on purpose—so broken or drifting installs are caught early. |
| **`packageManager` in `package.json`** | Tells **Corepack** (ships with Node) which **pnpm version** to use so installs behave the same across machines. This is [official Node guidance](https://nodejs.org/api/corepack.html) for pinning the package manager. |

---

## Why are there **two** `pnpm-lock.yaml` files?

1. **Repository root** — Tailwind v4, PostCSS, and the command that runs `tsc` for `web_dashboard/tsconfig.json` live with the **root** `package.json`.
2. **`web_dashboard/`** — A second `package.json` (e.g. Vitest for TS tests) has its **own** lockfile.

They are **two separate Node “projects”** in one repo. When you change dependencies, update the lockfile in the **same folder** as the `package.json` you changed.

---

## What you actually run (typical)

1. **First time or after pulling changes** (from repo root, with [pnpm](https://pnpm.io/installation) or `npx pnpm@9.15.9`):

   ```bash
   pnpm install --frozen-lockfile
   cd web_dashboard && pnpm install --frozen-lockfile && cd ..
   ```

   Use **`pnpm install`** (without `--frozen-lockfile`) only when you **intentionally** added or bumped a package and need to **refresh** the lockfile; then **commit** the updated `pnpm-lock.yaml`.

2. **Build CSS/JS** (from repo root): `pnpm run build:css`, `pnpm run build:ts`, or `pnpm run build` for both.

**Windows:** If `corepack enable` errors with permission under `Program Files`, use a global pnpm install or run commands via `npx pnpm@9.15.9 ...` (same version as in `package.json` → `packageManager`).

---

## Docker (`web_dashboard/Dockerfile.frontend`)

The image that compiles Tailwind/TypeScript **copies both lockfiles** and runs **`pnpm install --frozen-lockfile`**. That matches **best practice for reproducible builds**: production-like images should not “float” to whatever the registry returns today without a lockfile change and review.

---

## CI (Woodpecker)

On pull requests, a step runs **frozen pnpm installs** plus **`pnpm run test:ts`** so a bad or out-of-sync lockfile breaks the pipeline before merge.

---

## Summary (best practice checklist)

- **Commit** both `pnpm-lock.yaml` files whenever dependencies change.
- **CI/Docker:** use **`--frozen-lockfile`** so installs are reproducible and mismatches fail fast.
- **Local dev:** use frozen install when you only want to sync to the repo; use a normal `pnpm install` when you are **changing** dependencies, then commit the lockfile.

This does **not** replace general supply-chain hygiene (reviewing dependency PRs, etc.); it **does** ensure the project’s **recorded** dependency tree is what gets installed in automation and in Docker.

# TypeScript Source Files

**New to how JS deps work in this repo?** Read the plain guide: [`docs/frontend_dependencies.md`](../../../docs/frontend_dependencies.md) (lockfiles, pnpm, CI/Docker).

## ⚠️ IMPORTANT: Edit TypeScript Files, Not Compiled JavaScript

**All JavaScript files in `../static/js/` are automatically generated from TypeScript source files in this directory.**

### ✅ DO:
- Edit TypeScript files in `src/js/*.ts`
- Run `pnpm run build:ts` to compile changes (from repo root; see `AGENTS.md` for installs)
- Commit TypeScript source files to git

### ❌ DON'T:
- Edit files in `static/js/*.js` directly (they will be overwritten)
- Commit changes to compiled JavaScript files
- Manually modify the output files

## Build Process

1. **Source Files**: `src/js/*.ts` (TypeScript)
2. **Compilation**: `pnpm run build:ts` or `tsc -p web_dashboard/tsconfig.json`
3. **Output Files**: `static/js/*.js` (JavaScript - auto-generated)
4. **Served At**: `/assets/js/*.js` (via Flask's static file handler)

## File Structure

```
web_dashboard/
├── src/js/          ← EDIT THESE FILES (TypeScript)
│   ├── dashboard.ts
│   ├── jobs.ts
│   └── ...
└── static/js/       ← AUTO-GENERATED (Don't edit!)
    ├── dashboard.js
    ├── jobs.js
    └── ...
```

## Development Workflow

1. Make changes to `.ts` files in `src/js/`
2. Run build: `pnpm run build:ts`
3. Test your changes
4. Commit the `.ts` files (not the `.js` files)

## TypeScript Configuration

See `web_dashboard/tsconfig.json` for compiler settings.

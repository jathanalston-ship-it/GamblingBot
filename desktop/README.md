# MRP Desktop

Desktop application for the Momentum Research Platform — **Electron** shell +
**React/TypeScript/Tailwind** renderer over the **FastAPI/SQLite** backend.

See [`../docs/DESKTOP_APP.md`](../docs/DESKTOP_APP.md) for the full architecture
and implementation plan.

## Layout

```
desktop/
  electron/      Electron main + preload (spawns the FastAPI sidecar)
  renderer/      React + TS + Tailwind UI (Vite)
  package.json   orchestrates dev / build / package
```

## Prerequisites

- Node.js ≥ 20, npm ≥ 10
- The Python backend installed in the repo root: `make install`
  (the dev sidecar runs `python -m momentum.api`)

## Develop

```bash
cd desktop
npm install
npm run dev        # starts Vite (5173) + Electron; Electron spawns the backend
```

Set `MRP_PYTHON` to point at the repo's virtualenv interpreter if `python3` on
your PATH is not the right one.

## Build & package

```bash
npm run build      # renderer -> renderer/dist, electron -> dist-electron
npm run package    # electron-builder -> release/ (per-OS installer)
```

Packaging expects the backend frozen to `build/backend/` (PyInstaller); see the
docs for the one-file build command.

## Useful scripts

| Script | What |
|---|---|
| `npm run dev` | full dev loop (Vite + Electron + backend) |
| `npm run typecheck` | typecheck renderer + electron |
| `npm run build` | production build of renderer + electron main |
| `npm run package` | build installers via electron-builder |

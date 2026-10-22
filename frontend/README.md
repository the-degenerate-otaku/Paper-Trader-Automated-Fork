# Paper Trader frontend

Run `npm ci`, then `npm run dev` with the local Python API on port 2080.
`npm run build` type-checks and lints all source before building `dist`.
`npm run test:connection` checks browser credential persistence and origin validation.

The default entry is `src/pages/PaperTerminal.tsx`. The research workspace loads
on demand at `/?workspace=research` through `src/ResearchWorkspace.tsx`.
Both workspaces retain their existing design systems; see the root `DESIGN.md`.
The inherited pages without an import path from `src/main.tsx` have been removed.
MUI, Data Grid, Recharts and Lightweight Charts remain required by research tools.
The API compatibility exports in `src/services` remain available.

# Research workspace contexts

`ResearchWorkspace.tsx` wraps `Terminal.tsx` in `LoadingProvider` and `AccountProvider`.
`AccountContext.tsx` supplies account selection, refresh, validation and local caching.
`LoadingContext.tsx` supplies keyed loading state used by `PortfolioValue.tsx`.
Remote sessions do not read or write the account cache. The primary paper terminal
uses its own server snapshot and does not mount these providers.

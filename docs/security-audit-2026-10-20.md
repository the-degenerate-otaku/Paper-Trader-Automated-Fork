# Security test report

Repository: https://github.com/the-degenerate-otaku/Paper-Trader-Automated-Fork

Reviewed commit: `b005660fffa73874cd3c113b43e9e5952ffce3d4` (main snapshot downloaded on 2026-10-20).

## Result

Two known vulnerabilities were reproduced safely in an installation made from the committed `uv.lock`. Both originate in Starlette 0.47.2. The separate `requirements-tested-windows-py311.txt` specifies Starlette 1.9.0 and its advisory audit was clean. Do not interpret these findings as proof that a currently running installation uses the vulnerable versions.

The Python audit returned 36 advisory records across nine packages. There are **20 distinct package/advisory-ID pairs** after duplicate records are removed. Only the two findings below were reproduced through the application; the remaining advisory records are dependency exposure, not 18 additional confirmed application exploits.

## 1. Windows static-file requests reach UNC resolution before validation

**Priority: high when deploying the locked dependencies on Windows with the frontend served by the app.**

- Advisory: [CVE-2026-48818 / GHSA-wqp7-x3pw-xc5r](https://github.com/Kludex/starlette/security/advisories/GHSA-wqp7-x3pw-xc5r).
- Vulnerable pin: [uv.lock:1705](https://github.com/the-degenerate-otaku/Paper-Trader-Automated-Fork/blob/b005660fffa73874cd3c113b43e9e5952ffce3d4/uv.lock#L1705).
- App exposure: [api.py:733](https://github.com/the-degenerate-otaku/Paper-Trader-Automated-Fork/blob/b005660fffa73874cd3c113b43e9e5952ffce3d4/src/paper_trader/api.py#L733).

A crafted static-file URL reaches Windows filesystem resolution as a network share path. Windows can initiate outbound SMB authentication before Starlette rejects the path, potentially disclosing NTLMv2 authentication material.

**Evidence:** An in-process GET to `/%5C%5Csecurity-test.invalid%5Cshare%5Cprobe`, through the application's real middleware and static mount, reached `os.path.realpath` with `\\security-test.invalid\share\probe`. The harness intercepted and aborted that call before filesystem/network access. This proves the dangerous path is reachable; it does not claim that credentials were actually sent or captured.

The static mount was exercised with a synthetic asset in `frontend/dist`; a real frontend build was not needed for this path test. The mount is enabled only when that directory exists.

**Fix:** Regenerate the lockfile using compatible patched dependencies. This advisory is fixed in Starlette 1.1.0; other audited Starlette issues require at least 1.3.1. Prefer reconciling the lock with the newer tested snapshot, then retest. Reject UNC/device paths before filesystem resolution as defense in depth.

## 2. Crafted Range headers consume quadratic CPU time while serving files

**Priority: medium in the documented loopback deployment; higher if exposed to untrusted network clients.**

- Advisory: [CVE-2025-62727 / GHSA-7f5h-v6xp-fcq8](https://github.com/Kludex/starlette/security/advisories/GHSA-7f5h-v6xp-fcq8).
- Same vulnerable pin and static mount as finding 1.
- Additional FileResponse usage: [api.py:438](https://github.com/the-degenerate-otaku/Paper-Trader-Automated-Fork/blob/b005660fffa73874cd3c113b43e9e5952ffce3d4/src/paper_trader/api.py#L438).

The locked Starlette parser spends disproportionate CPU time processing malformed Range headers. A request eventually returning HTTP 400 does not prevent the resource consumption.

**Evidence:** Bounded requests to a synthetic static asset through the app took approximately:

| Numeric padding in Range | Response | Duration |
|---|---|---|
| 4,000 bytes | 400 | 0.052 s |
| 8,000 bytes | 400 | 0.211 s |
| 16,000 bytes | 400 | 0.875 s |

Doubling input roughly quadrupled processing time. The app's 64 KiB request-body limit does not constrain this header. These were in-process HTTP tests, not a sustained load attack or a measurement of Uvicorn's network-header limits.

**Fix:** Upgrade Starlette; this issue alone is fixed in 0.49.1. Use a version addressing all current advisories, regenerate the lock, and add a bounded Range-header regression check.

## Exposure boundaries

The documented listener binds to loopback. Host and explicit malicious Origin requests were rejected. Native local processes are explicitly trusted by the design, so absence of user authentication is not reported as a separate vulnerability.

However, GET requests without Origin are accepted, including a test request carrying `Sec-Fetch-Site: cross-site`. Thus Origin rejection alone is not a complete barrier against browser-triggered GETs. Actual exploit delivery through a particular browser and its local-network protections was not tested. No internet-facing deployment was attacked.

## Why existing checks missed the dependencies

[CI installs with `pip install -e ".[dev]"`](https://github.com/the-degenerate-otaku/Paper-Trader-Automated-Fork/blob/b005660fffa73874cd3c113b43e9e5952ffce3d4/.github/workflows/ci.yml#L29), resolving current versions rather than installing `uv.lock`. The reviewed lock retains older transitive packages. This explains how fresh installs and the newer tested snapshot can pass audits while a frozen installation remains vulnerable.

Add a frozen-lock CI job (`uv sync --frozen --extra dev`) and audit that environment. Keep the documented install, tested snapshot, and lockfile aligned.

## All affected locked packages

Fix versions below address the returned advisories, not a guarantee about future advisories or compatibility. Development tools are included because the audit installed the dev extra.

| Package | Locked version | Distinct advisory IDs | Fix floor for returned advisories |
|---|---|---:|---|
| anyio | 4.9.0 | 2 | 4.14.2 |
| idna | 3.10 | 1 | 3.15 |
| protobuf | 6.31.1 | 1 | 6.33.5 on the 6.x line |
| pygments | 2.19.2 | 1 | 2.20.0 |
| pytest | 8.4.1 | 1 | 9.0.3 |
| python-dotenv | 1.1.1 | 1 | 1.2.2 |
| requests | 2.32.4 | 1 | 2.33.0 |
| starlette | 0.47.2 | 6 | 1.3.1 |
| urllib3 | 2.5.0 | 6 | 2.8.0 |

The full advisory identifiers and fixes are listed in the appendix below. Several require features or conditions not demonstrated here, including Unicode hostnames, dotenv file rewriting, specialized proxy configurations, form parsing, or development-tool use. The application's Host allowlist also mitigates the reported Starlette malformed-Host issue.

## Executed checks

| Check | Result |
|---|---|
| Frozen dependency install | Completed with Python 3.11.15 |
| Repository pytest suite | 123 passed in 67.85 seconds |
| Live loopback HTTP security smoke | All 13 checks passed; temporary server stopped |
| Bandit over active `src` | Zero findings; 4,730 lines scanned |
| npm lockfile audit | Zero advisories |
| pip-audit of frozen Python environment | 36 records, 20 distinct package/advisory pairs, nine packages |
| Audit of tested Windows requirements pins | Zero known advisories; pins audited without reinstalling |
| Repository privacy-pattern scan | 3,102 file versions; zero blocking findings |
| Custom safe probes | UNC resolver reachability and Range CPU growth reproduced |

The initial sandbox test attempt encountered temporary-directory permission errors. The final full suite ran successfully with a dedicated workspace test directory outside those restrictions.

The history scan covered fetched main history/tags and working files, with inherited upstream attribution separated (363 email matches and 60 home-path matches). It uses the repository's limited credential patterns; it does not prove the absence of every secret.

Archived `upstream_reference` code was not installed or treated as an active attack surface. No production data, real credentials, live brokerage operations, or third-party attack targets were used. The audit did not modify application source or remediate the findings.

## Dependency advisory appendix

### anyio 4.9.0

- PYSEC-2026-4024 (CVE-2026-64847, GHSA-5p39-cfhj-2xmp). Fixed versions: 4.14.2.
- PYSEC-2026-4025 (CVE-2026-63374, GHSA-82r6-8w77-94w6). Fixed versions: 4.14.2.

### idna 3.10

- PYSEC-2026-215 (CVE-2026-45409, GHSA-65pc-fj4g-8rjx). Fixed versions: 3.15.

### protobuf 6.31.1

- PYSEC-2026-1805 (CVE-2026-0994, GHSA-7gcm-g887-7qv7). Fixed versions: 5.29.6, 6.33.5.

### pygments 2.19.2

- PYSEC-2026-2987 (CVE-2026-4539, GHSA-5239-wwwm-4pmq). Fixed versions: 2.20.0.

### pytest 8.4.1

- PYSEC-2026-1845 (CVE-2025-71176, GHSA-6w46-j5rx-g56g). Fixed versions: 9.0.3.

### python-dotenv 1.1.1

- PYSEC-2026-2270 (CVE-2026-28684, GHSA-mf9w-mj56-hr94). Fixed versions: 1.2.2.

### requests 2.32.4

- PYSEC-2026-2275 (CVE-2026-25645, GHSA-gc5v-m9x4-r6x2). Fixed versions: 2.33.0.

### starlette 0.47.2

- PYSEC-2026-161 (CVE-2026-48710, GHSA-86qp-5c8j-p5mr, X41-2026-002). Fixed versions: 1.0.1.
- PYSEC-2026-1942 (CVE-2025-62727, GHSA-7f5h-v6xp-fcq8). Fixed versions: 0.49.1.
- PYSEC-2026-2280 (CVE-2026-48817, GHSA-x746-7m8f-x49c). Fixed versions: 1.1.0.
- PYSEC-2026-2281 (CVE-2026-48818, GHSA-wqp7-x3pw-xc5r). Fixed versions: 1.1.0.
- PYSEC-2026-248 (CVE-2026-54282, GHSA-jp82-jpqv-5vv3). Fixed versions: 1.3.0.
- PYSEC-2026-249 (CVE-2026-54283, GHSA-82w8-qh3p-5jfq). Fixed versions: 1.3.1.

### urllib3 2.5.0

- PYSEC-2026-141 (CVE-2026-44431, GHSA-qccp-gfcp-xxvc). Fixed versions: 2.7.0.
- PYSEC-2026-1994 (CVE-2025-66471, GHSA-2xpw-w6gg-jr37). Fixed versions: 2.6.0.
- PYSEC-2026-1996 (CVE-2026-21441, GHSA-38jv-5279-wg99). Fixed versions: 2.6.3.
- PYSEC-2026-1998 (CVE-2025-66418, GHSA-gm62-xv2j-4w53). Fixed versions: 2.6.0.
- PYSEC-2026-4175 (CVE-2026-97687, GHSA-8988-9cw3-xx77). Fixed versions: 2.8.0.
- PYSEC-2026-4177 (CVE-2026-97689, GHSA-vxq7-64xx-v4gw). Fixed versions: 2.8.0.



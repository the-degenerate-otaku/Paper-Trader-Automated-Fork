# Reference audit

Verified 2026-10-20 using GitHub repository metadata, latest commit, root contents, and source files. These pins are an inspection snapshot, not automatically installed dependencies.

| Repository | License | Latest commit UTC | Commit | Root layout |
| --- | --- | --- | --- | --- |
| [buberlo/jev-trader](https://github.com/buberlo/jev-trader) | MIT | 09/19/2026 22:31:31 | 15d089e656d968fabb750bde8ebeec6d0da1ac7d | .env.example, .github, .gitignore, .python-version, LICENSE, PLAN.md, README.md, pyproject.toml, src, tests, uv.lock |
| [freqtrade/freqtrade](https://github.com/freqtrade/freqtrade) | GPL-3.0 | 10/20/2026 04:46:28 | 7ff17f5f5ac2f7bbc55a2937fd493a68c9951647 | .coveragerc, .devcontainer, .dockerignore, .gitattributes, .github, .gitignore, .pre-commit-config.yaml, .pylintrc, .vscode, CONTRIBUTING.md, Dockerfile, LICENSE |
| [jarrodwatts/jev-trader](https://github.com/jarrodwatts/jev-trader) | MIT | 10/13/2026 04:21:23 | d6254bf36a7875e009533fb722c1af8977b96e2d | .cursor, .dockerignore, .env.example, .gitignore, CLAUDE.md, Dockerfile, LICENSE, README.md, SPEC.md, bun.lock, bunfig.toml, index.ts |
| [marketcalls/openalgo-desktop](https://github.com/marketcalls/openalgo-desktop) | AGPL-3.0 | 10/20/2026 08:53:40 | a3441589195b89f97d1075595876c5bb00ee4d4f | .claude, .github, .gitignore, .trivyignore, CHANGELOG.md, CLAUDE.md, IMPLEMENTATION_PLAN.md, License.md, MIGRATION_TRACKER.md, README.md, biome.json, components.json |
| [NandhaKishorM/laya](https://github.com/NandhaKishorM/laya) | Apache-2.0 | 10/19/2026 09:39:55 | ffc142012af63d015fa19f05f29f9c5ff329a2cc | .dockerignore, .envrc, .gitattributes, .github, .gitignore, .gitleaksignore, AGENTS.md, BENCHMARKS.md, CODE_OF_CONDUCT.md, CONTRIBUTING.md, Dockerfile, LICENSE |
| [Open-Agent-Tools/open-paper-trading-mcp](https://github.com/Open-Agent-Tools/open-paper-trading-mcp) | Apache-2.0 | 10/09/2025 19:18:43 | 3c48168bc78e7c34b0c8247543349b02ee5aefd2 | .dockerignore, .editorconfig, .env.example, .github, .gitignore, .pre-commit-config.yaml, .vscode, CLAUDE.md, CODE_OF_CONDUCT.md, CONTRIBUTING.md, DOCKER_SETUP.md, Dockerfile |
| [Open-Papertrade/Open-Papertrade](https://github.com/Open-Papertrade/Open-Papertrade) | AGPL-3.0 | 07/23/2026 13:27:45 | 8fb144f694fdcf833241da5c5581852d06db1684 | .gitignore, CONTRIBUTING.md, LICENSE, README.md, backend, demo.gif, docs, frontend-ui |
| [razorback16/openjev](https://github.com/razorback16/openjev) | Apache-2.0 | 10/13/2026 03:40:11 | b4339c640f5331ef75098637d1be2c787715ee88 | .dockerignore, .gitignore, CHANGELOG.md, LICENSE, README.md, docker-compose.yml, docker, openjev, pyproject.toml, scripts, tests |

## Laya contract confirmed from source

The native server is installed with `python -m pip install "laya[serve]"`; the `laya-serve` entry point resolves to `laya.serve:main`. `POST /v1/systemone` accepts a state, optional model name and typed questions. `GET /health` is the health probe. The current router defaults to `convaiinnovations/laya` with subfolder `typed-decisions`. The standalone `convaiinnovations/laya-typed-decisions` is also recognized: the original brief's checkpoint is valid, but `model: "typed-decisions"` explicitly pins the router and avoids automatic language routing.

Source: [router.py](https://github.com/NandhaKishorM/laya/blob/ffc142012af63d015fa19f05f29f9c5ff329a2cc/laya/router.py), [serve.py](https://github.com/NandhaKishorM/laya/blob/ffc142012af63d015fa19f05f29f9c5ff329a2cc/laya/serve.py), and [pyproject.toml](https://github.com/NandhaKishorM/laya/blob/ffc142012af63d015fa19f05f29f9c5ff329a2cc/pyproject.toml).

A verified request shape for later integration:

```json
{
  "model": "typed-decisions",
  "state": {"body": "Asset: SAMPLE | Position: FLAT"},
  "questions": {
    "direction": {
      "type": "choice",
      "instructions": "Which direction does the available OHLCV evidence favor?",
      "criteria": {"LONG": "upward", "SHORT": "downward", "NEUTRAL": "no clear direction"}
    },
    "entry_conviction": {
      "type": "score",
      "instructions": "How strong is the evidence for entry?",
      "criteria": ["LOW", "MEDIUM", "HIGH"]
    },
    "reversal_risk": {"type": "noul", "instructions": "Is a reversal likely?"}
  }
}
```

The response has `model`, `answers`, and `usage`, with optional Laya extensions unless strict Jev mode is enabled. `choice` carries named probabilities, `score` is a numeric weighted level index (not a string such as MEDIUM), and `noul` is a probability. Entropy confidence is different from Jev's legacy confidence formula. Policy must use the selected answer's probability and calibrated thresholds rather than treating these confidence measures as interchangeable. This contract has been source-inspected, not tested against a running local server.

For the later CPU server, bind `LAYA_HOST=127.0.0.1`, `LAYA_DEVICE=cpu`, `LAYA_MODELS=typed-decisions`, and `LAYA_MAX_LOADED=1` before starting `laya-serve`. The native server preloads by default, so restrict the model list. ONNX exists in the upstream SDK; native HTTP-server ONNX/OpenVINO deployment has not been verified and is not promised here. Never interpret upstream GPU benchmark latency as this laptop's CPU latency.

## Other implementation findings

OpenJev supports the requested small encoder backends: `OPENJEV_BACKEND=laya` or `verdict`, with `OPENJEV_DEVICE=cpu`. Its default backend is GPU-oriented `vllm`, so it must never be launched with defaults on this machine. The model identifiers in its README include `laya-1.0` and `verdict-1.4`. Source: [OpenJev README](https://github.com/razorback16/openjev/blob/b4339c640f5331ef75098637d1be2c787715ee88/README.md).

The Python port has `state`, `judgment`, `policy`, `risk`, `execution`, `loop`, `feeds`, and `calibration` packages. Its client imports `typesafe_sdk` and requires a hosted API key; its state and pricing modules assume L2 crypto order books. The original TypeScript repo uses Bun and a `web` dashboard. We will adapt the Python separation and batched judgment harness in Milestone 6, replace L2 features with OHLCV, use local HTTP, move thresholds into config, and fail closed on inference loss. The original synthetic market-making fallback is unsuitable for the requested no-new-entry fallback. Source: [Python client](https://github.com/buberlo/jev-trader/blob/15d089e656d968fabb750bde8ebeec6d0da1ac7d/src/jev_trader/judgment/client.py) and [loop](https://github.com/buberlo/jev-trader/blob/15d089e656d968fabb750bde8ebeec6d0da1ac7d/src/jev_trader/loop/engine.py).

Optional projects were inspected for existence, license, last commit, and layout. None is installed or copied. GPL/AGPL projects are pattern references only.

## Official NSE sources verified

- [NIFTY 50 constituents](https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv): HTTP 200, schema `Company Name,Industry,Symbol,Series,ISIN Code`.
- [NIFTY BANK constituents](https://www.niftyindices.com/IndexConstituent/ind_niftybanklist.csv): HTTP 200, same schema. Member counts are not hardcoded.
- [NSE holiday master](https://www.nseindia.com/api/holiday-master?type=trading): HTTP 200, `CM` segment used for the maintained 2026 calendar. Official [holiday page](https://www.nseindia.com/resources/exchange-communication-holidays) states that Muhurat timing requires a separate circular.

No charges are verified in this milestone. Charges, instrument-specific tick sizes and margin rules require source verification before simulator use in Milestone 4.

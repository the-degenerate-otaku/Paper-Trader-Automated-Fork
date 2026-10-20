# Local System One inference

The client implements the inspected Laya/Jev HTTP contract at POST /v1/systemone. Laya source pinned at ffc142012af63d015fa19f05f29f9c5ff329a2cc was checked: laya/serve.py, laya/agent.py, laya/common.py and README. Choice probabilities are keyed by option labels; score probabilities use string indices starting at zero and score is the expected ordinal level. The policy computes its own expected level from calibrated probabilities. Entropy confidence is never treated as the probability of the selected direction.

Install the server in a separate environment following [Laya](https://github.com/NandhaKishorM/laya). Its official serving extra is `laya[serve]` and command is `laya-serve`. Set LAYA_HOST=127.0.0.1, LAYA_DEVICE=cpu, LAYA_MODELS=typed-decisions and LAYA_MAX_LOADED=1. The native port is 8000. Configure the application endpoint and thresholds in config.yaml. The inspected router alias typed-decisions selects the typed decision checkpoint; the canonical bundled repository is convaiinnovations/laya with subfolder typed-decisions.

Each symbol cycle sends one request containing direction, regime, entry conviction, setup quality, reversal risk and volatility expansion questions. News is outside core scope. The request, returned payload, checkpoint, latency and sanitized failure are journaled. Direction probability, conviction and reversal thresholds gate entries; CNC shorts are refused. Deterministic execution risk remains authoritative.

Retries fit inside one total timeout budget. Environment proxies and redirects are disabled. Oversized, malformed, non-finite, missing or inconsistent probabilities fail closed. An unavailable server produces HOLD and an explicit decision reason. Existing positions continue through independent reflex stops in the event loop.

Contract tests use a mock HTTP transport. The actual checkpoint has not been downloaded or benchmarked in this environment; CPU latency and ONNX deployment are unverified. No profitable or calibrated NSE behavior is claimed. Calibration requires held-out NSE outcome data in milestone 9.

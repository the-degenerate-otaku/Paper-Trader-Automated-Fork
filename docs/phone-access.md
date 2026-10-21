# GitHub Pages frontend with a PC backend

The public frontend is published from the gh-pages built-artifact branch at https://the-degenerate-otaku.github.io/Paper-Trader-Automated-Fork/. It contains the application code and a connection screen, not account data, model weights, an access key or a hardcoded backend address. The GitHub Pages build uses the repository subpath and VITE_REMOTE_BACKEND=true. Ordinary local builds retain their existing same-origin behavior.

The existing GitHub login permits repository publishing but lacks workflow-management scope. Built-file branch publishing uses the existing permissions. docs/pages-workflow.yml retains an optional automatic-deployment template; it is not an active workflow. Rebuild and republish the artifact branch after frontend changes. Never publish the repository root or private runtime folders as the site artifact.

Phone requests go through an authenticated gateway bound to 127.0.0.1:2083 on the PC. That gateway forwards only API routes to the existing backend at 127.0.0.1:2080. The backend's local Host/origin/CSRF boundaries remain enabled. The gateway limits request and response sizes, rejects redirects and unexpected origins, rate-limits failed authentication and never forwards the access key upstream. Remote pages refresh snapshots through authenticated HTTP polling; WebSockets are used only by the ordinary local UI.

An explicitly approved HTTPS tunnel can connect a phone outside the PC's network to the gateway. The temporary Cloudflare tunnel transports portfolio responses and paper-trading commands through Cloudflare. It must not point directly to the unauthenticated backend or model server. Starting this external connection requires the specific tunnel approval requested in the chat. No automatic tunnel start or OS startup service is installed by the application.

## Start the protected local gateway

From the repository root, using the existing environment:

```powershell
.venv/Scripts/python.exe -m paper_trader.remote_gateway --origin https://the-degenerate-otaku.github.io
```

On Linux use .venv/bin/python. The private key is generated once in .secrets/phone-access.key. It is ignored by Git and is never printed by the launcher. Read it only on your own PC. The gateway needs the existing backend running on port 2080; it does not launch or restart the trading engine.

After explicitly approving external tunnel access, use an official, checksum-verified cloudflared client:

```powershell
cloudflared tunnel --url http://127.0.0.1:2083 --protocol http2 --no-autoupdate
```

Enter the HTTPS address printed by cloudflared and your private access key on the Pages connection screen. Do not put the key in a URL, workflow variable or committed file. The page keeps it only in the tab's memory and clears it on Disconnect or reload. Only the nonsecret server address is saved in browser storage; the remote research account cache is disabled.

The temporary address changes when the tunnel restarts. Closing the tunnel or turning off/sleeping the PC makes backend operations unavailable while the frontend stays published. The model, stream ingestion and trade execution continue on the PC. There is no uptime guarantee. An unavailable connection does not simulate new quotes, reconstruct missed fills or extend trading hours. Market-session and risk rules still govern all paper orders.

Stop the gateway and tunnel processes to end access. To rotate the key, stop the gateway, remove only .secrets/phone-access.key, restart the gateway and reconnect your devices. Keep the key and any private connection note outside Git and shared/public folders.

# GitHub Pages frontend with a PC backend

The public frontend is published from the gh-pages built-artifact branch at https://the-degenerate-otaku.github.io/Paper-Trader-Automated-Fork/. It contains the application code and a connection screen, not account data, model weights, an access key or a hardcoded backend address. The GitHub Pages build uses the repository subpath and VITE_REMOTE_BACKEND=true. Ordinary local builds retain their existing same-origin behavior.

The existing GitHub login permits repository publishing but lacks workflow-management scope. Built-file branch publishing uses the existing permissions. docs/pages-workflow.yml retains an optional automatic-deployment template; it is not an active workflow. Rebuild and republish the artifact branch after frontend changes. Never publish the repository root or private runtime folders as the site artifact.

Phone requests go through an authenticated gateway bound to 127.0.0.1:2083 on the PC. That gateway forwards only API routes to the existing backend at 127.0.0.1:2080. The backend's local Host/origin/CSRF boundaries remain enabled. The gateway limits request and response sizes, rejects redirects and unexpected origins, rate-limits failed authentication and never forwards the access key upstream. Remote pages refresh snapshots through authenticated HTTP polling; WebSockets are used only by the ordinary local UI.

Tailscale Serve connects the phone privately to the authenticated gateway. Install Tailscale on both devices, sign into the same network, and enable Serve/HTTPS when prompted. Keep access restricted to your own devices through your Tailscale access policy. Do not expose the unauthenticated backend or model server. No public Cloudflare tunnel is needed.

## Start the protected local gateway

From the repository root, using the existing environment:

```powershell
.venv/Scripts/python.exe -m paper_trader.remote_gateway --origin https://the-degenerate-otaku.github.io
```

On Linux use .venv/bin/python. The private key is generated once in .secrets/phone-access.key. It is ignored by Git and is never printed by the launcher. Read it only on your own PC. The gateway needs the existing backend running on port 2080; it does not launch or restart the trading engine.

After connecting Tailscale on the PC, enable private HTTPS forwarding:

```powershell
tailscale serve --bg http://127.0.0.1:2083
tailscale serve status
```

Enter the private HTTPS address printed by Tailscale and your access key on the Pages connection screen. Keep Tailscale connected on the phone. Do not put the key in a URL, workflow variable or committed file. Use Serve for private access; Funnel publishes services publicly and is unnecessary here.

The optional Remember this device checkbox saves the address and access key together in this browser's local storage only after a successful connection. It is unchecked by default. Saved logins reconnect automatically on reload or return. Disconnect ends the current session but preserves the saved login; Forget this device deletes the saved key and disconnects. Clearing this site's browser data also removes it. Without opting in, the key remains in tab memory and is lost on reload. The nonsecret last-used address is saved separately. The remote research account cache remains disabled.

Remember a login only on your own protected device: browser scripts on this origin and anyone with access to its browser profile can read a saved key. This is persistent browser storage, not an encrypted credential vault. The key is never included in the public build, backend address, logs or Git. Rotation of the backend key invalidates every previously saved copy.

Turning off Tailscale or sleeping/shutting down the PC makes backend operations unavailable while the frontend stays published. The model, stream ingestion and trade execution continue on the PC. There is no uptime guarantee. An unavailable connection does not simulate new quotes, reconstruct missed fills or extend trading hours. Market-session and risk rules still govern all paper orders.

To remove this Serve endpoint, run tailscale serve --https=443 off. Stop the gateway to end API access. To rotate the key, stop the gateway, remove only .secrets/phone-access.key, restart the gateway and reconnect your devices. Keep the key and any private connection note outside Git and shared/public folders.

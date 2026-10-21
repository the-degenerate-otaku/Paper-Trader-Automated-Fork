import { useCallback, useEffect, useState, type ReactNode, type FormEvent } from "react";
import { apiFetch, clearConnection, setConnection, readRememberedConnection, rememberConnection, forgetConnection, readLastOrigin } from "./connection";

export default function RemoteConnection({ children }: { children: ReactNode }) {
    const [ready, setReady] = useState(false);
    const [saved] = useState(readRememberedConnection);
    const [origin, setOrigin] = useState(saved?.origin ?? readLastOrigin());
    const [key, setKey] = useState(saved?.key ?? "");
    const [remember, setRemember] = useState(Boolean(saved));
    const [remembered, setRemembered] = useState(Boolean(saved));
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const connectTo = useCallback(async (address: string, accessKey: string, persist: boolean) => {
        setBusy(true);
        setError("");
        try {
            const normalizedOrigin = new URL(address.trim()).origin;
            setConnection(address.trim(), accessKey.trim());
            const response = await apiFetch("/api/paper", { signal: AbortSignal.timeout(15000) });
            if (!response.ok) throw new Error(response.status === 401 || response.status === 429
                ? "Access key rejected. Check the private connection file on your PC."
                : "PC backend unavailable. Check that the backend and connection are running.");
            const snapshot = await response.json();
            if (!Array.isArray(snapshot.positions) || !snapshot.portfolio) throw new Error("This address is not a paper-trading backend.");
            if (persist) {
                rememberConnection(normalizedOrigin, accessKey.trim());
            } else {
                forgetConnection();
            }
            try { localStorage.setItem("paper-backend-origin", normalizedOrigin); } catch { void 0; }
            setRemembered(persist);
            setKey("");
            setReady(true);
        } catch (e) {
            clearConnection();
            setError(e instanceof Error && e.message !== "Failed to fetch" ? e.message
                : "Cannot reach your PC. Check that it is online and the connection address is current.");
        } finally { setBusy(false); }
    }, []);
    useEffect(() => {
        if (saved) void connectTo(saved.origin, saved.key, true);
    }, [saved, connectTo]);
    function connect(event: FormEvent) {
        event.preventDefault();
        void connectTo(origin, key, remember);
    }
    function forget() {
        try { forgetConnection(); }
        catch { setError("Browser storage is unavailable. Clear this site’s browser data to remove its saved login."); return; }
        clearConnection();
        setReady(false);
        setKey("");
        setRemember(false);
        setRemembered(false);
    }
    if (ready) return <><div className="paper-app remote-session"><span>Connected to your PC</span>
        <div className="remote-actions"><button onClick={() => { clearConnection(); setReady(false); setKey(readRememberedConnection()?.key ?? ""); }}>Disconnect</button>
            {remembered && <button onClick={forget}>Forget this device</button>}</div></div>{children}</>;
    return <main className="paper-app remote-connection"><h1>Paper Trader</h1>
        <section aria-labelledby="connection-heading"><h2 id="connection-heading">Connect to your PC</h2>
            <p>Your portfolio and trading engine run on your computer. Keep it online while using this terminal.</p>
            <form onSubmit={connect}>
                <label htmlFor="backend-origin">PC connection address</label>
                <input id="backend-origin" type="url" maxLength={256} value={origin}
                    onChange={e => setOrigin(e.target.value)} required autoComplete="url" placeholder="https://your-pc.your-tailnet.ts.net" disabled={busy} />
                <label htmlFor="access-key">Access key</label>
                <input id="access-key" type="password" maxLength={256} value={key}
                    onChange={e => setKey(e.target.value)} required autoComplete="off" disabled={busy} />
                <label className="remember-device"><input type="checkbox" checked={remember} disabled={busy}
                    onChange={e => setRemember(e.target.checked)} />Remember this device</label>
                <p className="muted">{remember ? "Saves your access key in this browser and reconnects when you return. Use only on your own device. Disconnect keeps the saved login." : "Your access key stays in this tab’s memory unless you choose to remember this device."}</p>
                {error && <p role="alert">{error}</p>}
                <button className="primary" disabled={busy}>{busy ? "Connecting…" : "Connect"}</button>
                {remembered && <button type="button" onClick={forget} disabled={busy}>Forget this device</button>}
            </form></section></main>;
}

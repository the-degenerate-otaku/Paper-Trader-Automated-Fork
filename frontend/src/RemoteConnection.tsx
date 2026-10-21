import { useState, type ReactNode, type FormEvent } from "react";
import { apiFetch, clearConnection, setConnection } from "./connection";

export default function RemoteConnection({ children }: { children: ReactNode }) {
    const [ready, setReady] = useState(false);
    const [origin, setOrigin] = useState(localStorage.getItem("paper-backend-origin") ?? "");
    const [key, setKey] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    async function connect(event: FormEvent) {
        event.preventDefault();
        setBusy(true);
        setError("");
        try {
            setConnection(origin.trim(), key.trim());
            const response = await apiFetch("/api/paper", { signal: AbortSignal.timeout(15000) });
            if (!response.ok) throw new Error(response.status === 401 || response.status === 429
                ? "Access key rejected. Check the private connection file on your PC."
                : "PC backend unavailable. Check that the backend and connection are running.");
            const snapshot = await response.json();
            if (!Array.isArray(snapshot.positions) || !snapshot.portfolio) throw new Error("This address is not a paper-trading backend.");
            localStorage.setItem("paper-backend-origin", origin.trim());
            setKey("");
            setReady(true);
        } catch (e) {
            clearConnection();
            setError(e instanceof Error && e.message !== "Failed to fetch" ? e.message
                : "Cannot reach your PC. Check that it is online and the connection address is current.");
        } finally { setBusy(false); }
    }
    if (ready) return <><div className="paper-app remote-session"><span>Connected to your PC</span>
        <button onClick={() => { clearConnection(); setReady(false); }}>Disconnect</button></div>{children}</>;
    return <main className="paper-app remote-connection"><h1>Paper Trader</h1>
        <section aria-labelledby="connection-heading"><h2 id="connection-heading">Connect to your PC</h2>
            <p>Your portfolio and trading engine run on your computer. Keep it online while using this terminal.</p>
            <form onSubmit={connect}>
                <label htmlFor="backend-origin">PC connection address</label>
                <input id="backend-origin" type="url" maxLength={256} value={origin}
                    onChange={e => setOrigin(e.target.value)} required autoComplete="url" placeholder="https://your-connection.trycloudflare.com" />
                <label htmlFor="access-key">Access key</label>
                <input id="access-key" type="password" maxLength={256} value={key}
                    onChange={e => setKey(e.target.value)} required autoComplete="off" />
                <p className="muted">Find these in the private connection file on your PC. The access key stays in this tab’s memory.</p>
                {error && <p role="alert">{error}</p>}
                <button className="primary" disabled={busy}>{busy ? "Connecting…" : "Connect"}</button>
            </form></section></main>;
}

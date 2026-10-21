export const remoteMode = import.meta.env.VITE_REMOTE_BACKEND === "true";
let connection: { origin: string; key: string } | null = null;
const rememberedConnectionKey = "paper-remembered-connection";

export function readRememberedConnection(): { origin: string; key: string } | null {
    try {
        const saved = JSON.parse(localStorage.getItem(rememberedConnectionKey) ?? "null");
        if (saved && typeof saved.origin === "string" && typeof saved.key === "string" &&
            saved.origin.length <= 256 && /^[A-Za-z0-9_-]{32,256}$/.test(saved.key)) {
            return { origin: saved.origin, key: saved.key };
        }
    } catch { return null; }
    return null;
}

export function rememberConnection(origin: string, key: string) {
    try { localStorage.setItem(rememberedConnectionKey, JSON.stringify({ origin, key })); }
    catch { throw new Error("This browser cannot save the login. Uncheck Remember this device to connect for this session."); }
}

export function forgetConnection() {
    localStorage.removeItem(rememberedConnectionKey);
}

export function readLastOrigin() {
    try { return localStorage.getItem("paper-backend-origin") ?? ""; }
    catch { return ""; }
}

export function setConnection(origin: string, key: string) {
    const url = new URL(origin);
    const local = url.protocol === "http:" && ["127.0.0.1", "localhost"].includes(url.hostname);
    if ((!local && url.protocol !== "https:") || url.username || url.password ||
        url.search || url.hash || !["", "/"].includes(url.pathname)) {
        throw new Error("Enter the secure PC connection address, without a path or access key.");
    }
    connection = { origin: url.origin, key };
}

export function clearConnection() { connection = null; }

export function apiFetch(path: string, init: RequestInit = {}) {
    if (!remoteMode) return fetch(path, init);
    if (!connection) return Promise.reject(new Error("Connect to your PC first."));
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${connection.key}`);
    return fetch(`${connection.origin}${path}`, { ...init, headers, credentials: "omit", cache: "no-store",
        signal: init.signal ?? AbortSignal.timeout(35000) });
}

export function pollSnapshot<T>(path: string, update: (data: T) => void, status: (connected: boolean) => void) {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    const poll = async () => {
        try {
            const response = await apiFetch(path, { signal: AbortSignal.any([controller.signal, AbortSignal.timeout(35000)]) });
            if (!response.ok) throw new Error("Backend unavailable");
            const data: T = await response.json();
            if (active) { update(data); status(true); }
        } catch { if (active) status(false); }
        finally { if (active) timer = setTimeout(poll, 1000); }
    };
    void poll();
    return () => { active = false; clearTimeout(timer); controller.abort(); };
}

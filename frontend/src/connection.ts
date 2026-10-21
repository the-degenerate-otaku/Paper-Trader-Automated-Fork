export const remoteMode = import.meta.env.VITE_REMOTE_BACKEND === "true";
let connection: { origin: string; key: string } | null = null;

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

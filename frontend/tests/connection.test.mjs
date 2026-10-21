import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

function fixture() {
    const values = new Map();
    const requests = [];
    const storage = {
        getItem: key => values.get(key) ?? null,
        setItem: (key, value) => values.set(key, value),
        removeItem: key => values.delete(key),
    };
    const source = readFileSync(new URL("../src/connection.ts", import.meta.url), "utf8")
        .replace('import.meta.env.VITE_REMOTE_BACKEND === "true"', "true");
    const compiled = ts.transpileModule(source, {
        compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText;
    const context = { exports: {}, localStorage: storage, URL, Headers, AbortSignal,
        fetch: async (...args) => { requests.push(args); return new Response("{}"); },
        setTimeout, clearTimeout };
    vm.runInNewContext(compiled, context);
    return { api: context.exports, values, requests, storage };
}

const key = "test-only-key-for-browser-storage-123456789";

test("credentials persist only by explicit opt-in and survive disconnect", async () => {
    const { api, values, requests } = fixture();
    api.setConnection("https://example.ts.net", key);
    await api.apiFetch("/api/paper");
    assert.equal(values.size, 0);
    assert.equal(requests[0][1].headers.get("Authorization"), `Bearer ${key}`);
    assert.equal(requests[0][1].credentials, "omit");
    api.rememberConnection("https://example.ts.net", key);
    api.clearConnection();
    assert.equal(api.readRememberedConnection().key, key);
    await assert.rejects(api.apiFetch("/api/paper"), /Connect to your PC/);
    api.forgetConnection();
    assert.equal(api.readRememberedConnection(), null);
});

test("malformed and unavailable browser storage do not crash startup", () => {
    const { api, values, storage } = fixture();
    for (const raw of ["broken", "null", '{"origin":1,"key":2}', '{"origin":"https://example.ts.net","key":"short"}']) {
        values.set("paper-remembered-connection", raw);
        assert.equal(api.readRememberedConnection(), null);
    }
    storage.getItem = () => { throw new Error("Storage blocked"); };
    assert.equal(api.readRememberedConnection(), null);
    assert.equal(api.readLastOrigin(), "");
    storage.setItem = () => { throw new Error(key); };
    assert.throws(() => api.rememberConnection("https://example.ts.net", key), error =>
        error.message.includes("Uncheck Remember this device") && !error.message.includes(key));
});

test("restored credentials cannot be sent to insecure or decorated origins", () => {
    const { api, requests } = fixture();
    const decorated = new URL("https://example.ts.net");
    decorated.username = "test-user";
    decorated.password = "test-password";
    for (const origin of ["http://example.ts.net", decorated.href, "https://example.ts.net/path", "https://example.ts.net?key=private"]) {
        assert.throws(() => api.setConnection(origin, key));
    }
    assert.equal(requests.length, 0);
});

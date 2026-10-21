import { lazy, Suspense } from "react";
import PaperTerminal from "./pages/PaperTerminal";
import RemoteConnection from "./RemoteConnection";
import { remoteMode } from "./connection";
const ResearchWorkspace = lazy(() => import("./ResearchWorkspace"));
export default function App() {
    const workspace = new URLSearchParams(location.search).get("workspace") ===
        "research" ? (
        <Suspense fallback={<p>Loading research workspace...</p>}>
            <ResearchWorkspace />
        </Suspense>
    ) : (
        <PaperTerminal />
    );
    return remoteMode ? <RemoteConnection>{workspace}</RemoteConnection> : workspace;
}

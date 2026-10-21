import { lazy, Suspense } from "react";
import PaperTerminal from "./pages/PaperTerminal";
const ResearchWorkspace = lazy(() => import("./ResearchWorkspace"));
export default function App() {
    return new URLSearchParams(location.search).get("workspace") ===
        "research" ? (
        <Suspense fallback={<p>Loading research workspace...</p>}>
            <ResearchWorkspace />
        </Suspense>
    ) : (
        <PaperTerminal />
    );
}

import { CssBaseline, ThemeProvider } from "@mui/material";
import theme from "./theme";
import { AccountProvider } from "./contexts/AccountContext";
import { LoadingProvider } from "./contexts/LoadingContext";
import Terminal from "./pages/Terminal";
import PaperTerminal from "./pages/PaperTerminal";

export default function App() {
    return (
        <ThemeProvider theme={theme}>
            <CssBaseline />
            <LoadingProvider>
                <AccountProvider>
                    {new URLSearchParams(location.search).get("workspace") ===
                    "research" ? (
                        <Terminal />
                    ) : (
                        <PaperTerminal />
                    )}
                </AccountProvider>
            </LoadingProvider>
        </ThemeProvider>
    );
}

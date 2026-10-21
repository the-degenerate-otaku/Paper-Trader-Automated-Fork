import { CssBaseline, ThemeProvider } from "@mui/material";
import theme from "./theme";
import { AccountProvider } from "./contexts/AccountContext";
import { LoadingProvider } from "./contexts/LoadingContext";
import Terminal from "./pages/Terminal";

export default function ResearchWorkspace() {
    return (
        <ThemeProvider theme={theme}>
            <CssBaseline />
            <LoadingProvider>
                <AccountProvider>
                    <Terminal />
                </AccountProvider>
            </LoadingProvider>
        </ThemeProvider>
    );
}

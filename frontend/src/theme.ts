import { createTheme } from "@mui/material/styles";

export const FONTS = {
    primary: "Inter, system-ui, sans-serif",
    monospace: "Consolas, monospace",
} as const;
export default createTheme({
    palette: {
        mode: "dark",
        primary: { main: "#77dfb5" },
        secondary: { main: "#a5b5fb" },
        background: { default: "#0c1118", paper: "#131c27" },
        text: { primary: "#e3ebf3", secondary: "#8ea1b5" },
    },
    typography: {
        fontFamily: FONTS.primary,
        h4: { fontWeight: 650 },
        button: { textTransform: "none", fontWeight: 600 },
    },
    shape: { borderRadius: 12 },
    components: {
        MuiPaper: {
            defaultProps: { elevation: 0 },
            styleOverrides: {
                root: { backgroundImage: "none", border: "1px solid #253243" },
            },
        },
        MuiButton: { defaultProps: { disableElevation: true } },
    },
});

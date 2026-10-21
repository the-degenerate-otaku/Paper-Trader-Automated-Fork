import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App.tsx";

createRoot(document.getElementById("root")!).render(
    <StrictMode>
        <App />
    </StrictMode>,
);

const fontStyles = document.createElement("link");
fontStyles.rel = "stylesheet";
fontStyles.href =
    "https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&display=swap";
document.head.appendChild(fontStyles);

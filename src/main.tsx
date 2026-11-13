import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { seedBrowserStorage } from "./dev/seeds";
import { runtimeConfig } from "./config/runtime";
import App from "./App";
import "./index.css";
import "./App.css";

if (runtimeConfig.loadDemoSeed) seedBrowserStorage();


createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

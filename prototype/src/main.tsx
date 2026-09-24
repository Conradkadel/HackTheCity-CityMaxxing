import React from "react";
import { createRoot } from "react-dom/client";
import { UnifiedWorkspace } from "./UnifiedWorkspace";
import "./style.css";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <UnifiedWorkspace />
  </React.StrictMode>,
);

import React from "react";
import ReactDOM from "react-dom/client";
import { HashRouter } from "react-router-dom";

import App from "./App";
import { WorkspaceProvider } from "./state/workspace";
import "./index.css";

// HashRouter so client routing works under the file:// protocol when packaged.
// Startup-performance mark: React mounted (measured from page navigation start).
queueMicrotask(() => {
  try {
    window.mrp?.perf?.mark("renderer-hydrated", Math.round(performance.now()));
  } catch {
    /* instrumentation must never break the app */
  }
});

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <HashRouter>
      <WorkspaceProvider>
        <App />
      </WorkspaceProvider>
    </HashRouter>
  </React.StrictMode>,
);

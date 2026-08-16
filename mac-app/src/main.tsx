import React, { lazy, Suspense } from "react";
import ReactDOM from "react-dom/client";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { MenubarPopover } from "./components/menubar-popover/MenubarPopover";
import { initializeTheme } from "./utils/theme";
import "./index.css";

const MainApp = lazy(() => import("./MainApp"));
const MENUBAR_POPOVER_WINDOW_LABEL = "menubar-popover";
const cleanupTheme = initializeTheme();
window.addEventListener("pagehide", cleanupTheme, { once: true });

function detectCurrentWindowLabel() {
  try {
    return getCurrentWindow().label;
  } catch {
    return "main";
  }
}

function RootLoadingState() {
  return (
    <div className="grid h-screen w-screen place-items-center bg-[var(--ow-bg)]">
      <div className="h-5 w-5 animate-spin rounded-full border-2 border-[var(--ow-line)] border-t-[var(--ow-blue)]" />
    </div>
  );
}

const content =
  detectCurrentWindowLabel() === MENUBAR_POPOVER_WINDOW_LABEL ? (
    <MenubarPopover />
  ) : (
    <Suspense fallback={<RootLoadingState />}>
      <MainApp />
    </Suspense>
  );

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>{content}</React.StrictMode>
);

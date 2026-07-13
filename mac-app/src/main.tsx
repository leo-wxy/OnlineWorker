import React, { lazy, Suspense } from "react";
import ReactDOM from "react-dom/client";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { MenubarPopover } from "./components/menubar-popover/MenubarPopover";
import "./index.css";

const MainApp = lazy(() => import("./MainApp"));
const MENUBAR_POPOVER_WINDOW_LABEL = "menubar-popover";

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
      <div className="h-5 w-5 animate-spin rounded-full border-2 border-slate-200 border-t-blue-600" />
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

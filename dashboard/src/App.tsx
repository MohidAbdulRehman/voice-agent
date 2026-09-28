import { useState } from "react";
import { api } from "./api";
import { CallsView } from "./components/CallsView";
import { Header } from "./components/Header";
import { PatientsView } from "./components/PatientsView";
import { Tabs, type Tab } from "./components/Tabs";
import { useApi } from "./useApi";
import { POLL_MS, usePolling } from "./usePolling";

const DEFAULT_TIME_ZONE = "America/New_York";

type View = "patients" | "calls";

const TABS: readonly Tab<View>[] = [
  { id: "patients", label: "Patients" },
  { id: "calls", label: "Calls" },
];

// The calls tab has its own address, /dashboard/#calls, so it can be linked to.
function viewInUrl(): View {
  return window.location.hash === "#calls" ? "calls" : "patients";
}

function putViewInUrl(view: View): void {
  const { pathname, search } = window.location;
  window.history.replaceState(null, "", view === "calls" ? "#calls" : `${pathname}${search}`);
}

export function App() {
  const [view, setView] = useState<View>(viewInUrl);
  const [manualRefreshes, setManualRefreshes] = useState(0);
  // Both only ever go up, so their sum changes whenever either does.
  const refresh = usePolling(POLL_MS) + manualRefreshes;

  const config = useApi(api.config, "config");
  const settings = config.state === "ready" ? config.data : null;
  const timeZone = settings?.clinic_timezone ?? DEFAULT_TIME_ZONE;
  const viewProps = {
    timeZone,
    refresh,
    onRefresh: () => setManualRefreshes((count) => count + 1),
  };
  const choose = (next: View) => {
    setView(next);
    putViewInUrl(next);
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <Header config={settings} />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <Tabs label="Dashboard" tabs={TABS} selected={view} onSelect={choose} />
        {/* Only the open tab is rendered, so only its data is polled. */}
        {TABS.map((tab) => (
          <div
            key={tab.id}
            role="tabpanel"
            id={`panel-${tab.id}`}
            aria-labelledby={`tab-${tab.id}`}
            hidden={tab.id !== view}
            className={
              tab.id === view
                ? "mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]"
                : undefined
            }
          >
            {tab.id !== view ? null : view === "patients" ? (
              <PatientsView {...viewProps} />
            ) : (
              <CallsView {...viewProps} />
            )}
          </div>
        ))}
      </main>
    </div>
  );
}

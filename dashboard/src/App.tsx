import { useState } from "react";
import { api, searchQuery } from "./api";
import { Header } from "./components/Header";
import { PatientDetail } from "./components/PatientDetail";
import { PatientsTable } from "./components/PatientsTable";
import { NO_SEARCH, SearchForm } from "./components/SearchForm";
import type { PatientSearch } from "./types";
import { useApi } from "./useApi";

const DEFAULT_TIME_ZONE = "America/New_York";

export function App() {
  const [search, setSearch] = useState<PatientSearch>(NO_SEARCH);
  const [refreshes, setRefreshes] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const config = useApi(api.config, "config");
  const patients = useApi(
    (signal) => api.patients(search, signal),
    `patients${searchQuery(search)}:${refreshes}`,
  );

  const settings = config.state === "ready" ? config.data : null;
  const timeZone = settings?.clinic_timezone ?? DEFAULT_TIME_ZONE;
  const listed = patients.state === "ready" ? patients.data : [];
  const selected = listed.find((patient) => patient.patient_id === selectedId) ?? null;
  const badSearch = patients.state === "error" && patients.error.status === 400;

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <Header config={settings} />
      <main className="mx-auto grid max-w-7xl grid-cols-1 gap-6 px-4 py-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <section aria-labelledby="patients-heading" className="space-y-4">
          <div className="flex items-center justify-between gap-2">
            <h2 id="patients-heading" className="text-lg font-semibold">
              Patients
            </h2>
            <button
              type="button"
              onClick={() => setRefreshes((count) => count + 1)}
              className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700"
            >
              Refresh
            </button>
          </div>
          <SearchForm errors={badSearch ? patients.error.body.details : []} onSearch={setSearch} />
          {patients.state === "loading" ? (
            <p role="status" className="text-sm text-slate-600">
              Loading patients...
            </p>
          ) : null}
          {patients.state === "error" && !badSearch ? (
            <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-800">
              {patients.error.message}
            </p>
          ) : null}
          {patients.state === "ready" ? (
            <PatientsTable
              patients={patients.data}
              selectedId={selectedId}
              timeZone={timeZone}
              onSelect={setSelectedId}
            />
          ) : null}
        </section>
        <aside aria-label="Patient details" className="lg:sticky lg:top-6 lg:self-start">
          {selected ? (
            <PatientDetail
              key={selected.patient_id}
              patient={selected}
              timeZone={timeZone}
              refreshes={refreshes}
            />
          ) : (
            <p className="rounded-lg border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-600">
              Select a patient to see every field, their calls and their appointments.
            </p>
          )}
        </aside>
      </main>
    </div>
  );
}

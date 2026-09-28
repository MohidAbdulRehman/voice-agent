import { useState } from "react";
import { api, searchQuery } from "../api";
import type { PatientSearch } from "../types";
import { useApi } from "../useApi";
import { ListHeading } from "./ListHeading";
import { PatientDetail } from "./PatientDetail";
import { PatientsTable } from "./PatientsTable";
import { NO_SEARCH, SearchForm } from "./SearchForm";

interface PatientsViewProps {
  timeZone: string;
  /** Goes up on every poll and on Refresh. */
  refresh: number;
  onRefresh: () => void;
}

/** The patients tab: search, the newest patients, and the chosen patient's details. */
export function PatientsView({ timeZone, refresh, onRefresh }: PatientsViewProps) {
  const [search, setSearch] = useState<PatientSearch>(NO_SEARCH);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const patients = useApi(
    (signal) => api.patients(search, signal),
    `patients${searchQuery(search)}`,
    refresh,
  );

  const listed = patients.state === "ready" ? patients.data : [];
  const selected = listed.find((patient) => patient.patient_id === selectedId) ?? null;
  const badSearch = patients.state === "error" && patients.error.status === 400;

  return (
    <>
      <section aria-labelledby="patients-heading" className="space-y-4">
        <ListHeading
          id="patients-heading"
          title="Patients"
          result={patients}
          timeZone={timeZone}
          onRefresh={onRefresh}
        />
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
            refresh={refresh}
          />
        ) : (
          <p className="rounded-lg border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-600">
            Select a patient to see every field, their calls and their appointments.
          </p>
        )}
      </aside>
    </>
  );
}

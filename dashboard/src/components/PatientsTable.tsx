import { formatDateTime, formatPhone } from "../format";
import type { Patient } from "../types";

interface PatientsTableProps {
  patients: Patient[];
  selectedId: string | null;
  timeZone: string;
  onSelect: (patientId: string) => void;
}

export function PatientsTable({ patients, selectedId, timeZone, onSelect }: PatientsTableProps) {
  if (patients.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-slate-300 bg-white p-6 text-center text-sm text-slate-600">
        No patients match.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
      <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
        <caption className="sr-only">Patients, newest first. Select a name for details.</caption>
        <thead className="bg-slate-50 text-slate-700">
          <tr>
            <th scope="col" className="px-4 py-3 font-semibold">Name</th>
            <th scope="col" className="px-4 py-3 font-semibold">Date of birth</th>
            <th scope="col" className="px-4 py-3 font-semibold">Phone</th>
            <th scope="col" className="px-4 py-3 font-semibold">City</th>
            <th scope="col" className="hidden px-4 py-3 font-semibold md:table-cell">
              Language
            </th>
            <th scope="col" className="hidden px-4 py-3 font-semibold md:table-cell">
              Registered
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {patients.map((patient) => {
            const selected = patient.patient_id === selectedId;
            return (
              <tr key={patient.patient_id} className={selected ? "bg-teal-50" : "hover:bg-slate-50"}>
                <th scope="row" className="px-4 py-3 font-medium">
                  <button
                    type="button"
                    aria-pressed={selected}
                    onClick={() => onSelect(patient.patient_id)}
                    className="text-left text-teal-800 underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700"
                  >
                    {patient.last_name}, {patient.first_name}
                  </button>
                </th>
                <td className="px-4 py-3 whitespace-nowrap">{patient.date_of_birth}</td>
                <td className="px-4 py-3 whitespace-nowrap">{formatPhone(patient.phone_number)}</td>
                <td className="px-4 py-3">
                  {patient.city}, {patient.state}
                </td>
                <td className="hidden px-4 py-3 md:table-cell">{patient.preferred_language}</td>
                <td className="hidden px-4 py-3 whitespace-nowrap md:table-cell">
                  {formatDateTime(patient.created_at, timeZone)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

import { formatDialNumber } from "../format";
import type { DashboardConfig } from "../types";

export function Header({ config }: { config: DashboardConfig | null }) {
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-4">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">
            {config?.clinic_name ?? "Patient intake"}
          </h1>
          <p className="text-sm text-slate-600">Patient intake dashboard (read-only)</p>
        </div>
        {config?.phone_number ? (
          <p className="rounded-md bg-teal-50 px-3 py-2 text-sm text-teal-900">
            Call {config.assistant_name} to register:{" "}
            <a
              className="font-semibold underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700"
              href={`tel:${config.phone_number}`}
            >
              {formatDialNumber(config.phone_number)}
            </a>
          </p>
        ) : null}
      </div>
    </header>
  );
}

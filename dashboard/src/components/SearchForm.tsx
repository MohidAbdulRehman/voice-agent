import { useState, type FormEvent, type InputHTMLAttributes } from "react";
import type { FieldError } from "../api";
import type { PatientSearch } from "../types";

export const NO_SEARCH: PatientSearch = { last_name: "", date_of_birth: "", phone_number: "" };

interface SearchFormProps {
  /** Problems the API found with the last search, shown next to their boxes. */
  errors: FieldError[];
  onSearch: (search: PatientSearch) => void;
}

export function SearchForm({ errors, onSearch }: SearchFormProps) {
  const [search, setSearch] = useState<PatientSearch>(NO_SEARCH);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    onSearch(search);
  };
  const clear = () => {
    setSearch(NO_SEARCH);
    onSearch(NO_SEARCH);
  };
  const box = (name: keyof PatientSearch) => ({
    name,
    value: search[name],
    error: errors.find((error) => error.field === name)?.message,
    onChange: (value: string) => setSearch({ ...search, [name]: value }),
  });

  return (
    <form
      role="search"
      aria-label="Search patients"
      onSubmit={submit}
      className="grid grid-cols-1 gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:grid-cols-[repeat(3,minmax(0,1fr))_auto]"
    >
      <SearchBox label="Last name" autoComplete="off" {...box("last_name")} />
      <SearchBox
        label="Date of birth"
        placeholder="MM/DD/YYYY"
        inputMode="numeric"
        autoComplete="off"
        {...box("date_of_birth")}
      />
      <SearchBox
        label="Phone"
        placeholder="(512) 555-0100"
        type="tel"
        autoComplete="off"
        {...box("phone_number")}
      />
      <div className="flex items-start gap-2 sm:pt-6">
        <button
          type="submit"
          className="rounded-md bg-teal-700 px-4 py-2 text-sm font-semibold text-white hover:bg-teal-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700"
        >
          Search
        </button>
        <button
          type="button"
          onClick={clear}
          className="rounded-md border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700"
        >
          Clear
        </button>
      </div>
    </form>
  );
}

interface SearchBoxProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "name" | "value" | "onChange"> {
  label: string;
  name: keyof PatientSearch;
  value: string;
  error: string | undefined;
  onChange: (value: string) => void;
}

function SearchBox({ label, name, value, error, onChange, ...input }: SearchBoxProps) {
  const id = `search-${name}`;
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium text-slate-700">
        {label}
      </label>
      <input
        id={id}
        name={name}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        className="rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-500 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-teal-700 aria-invalid:border-red-700"
        {...input}
      />
      {error ? (
        <p id={`${id}-error`} className="text-sm text-red-700">
          {error}
        </p>
      ) : null}
    </div>
  );
}

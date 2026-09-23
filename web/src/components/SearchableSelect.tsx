import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";

export type SearchableOption = {
  value: string;
  label: string;
  /** Texto adicional para filtrar (p.ej. network_id) */
  searchText?: string;
};

type Props = {
  value: string;
  options: SearchableOption[];
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  emptyLabel?: string;
  /** Si true, permite valor vacío (opción "—") */
  allowEmpty?: boolean;
};

function norm(s: string): string {
  return (s || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toUpperCase()
    .trim();
}

/** Match por iniciales / prefijo / contiene (PA → PA217, PA108…) */
function matchesQuery(opt: SearchableOption, query: string): boolean {
  const q = norm(query);
  if (!q) return true;
  const hay = norm(`${opt.value} ${opt.label} ${opt.searchText || ""}`);
  if (hay.startsWith(q)) return true;
  if (hay.includes(q)) return true;
  // tokens: "PA 217" o "NET PA217"
  const tokens = hay.split(/[^A-Z0-9]+/).filter(Boolean);
  if (tokens.some((t) => t.startsWith(q))) return true;
  // iniciales consecutivas del código (P A → PA…)
  const code = norm(opt.value);
  if (code.startsWith(q)) return true;
  return false;
}

export function SearchableSelect({
  value,
  options,
  onChange,
  placeholder = "Buscar…",
  disabled = false,
  emptyLabel = "— elegir —",
  allowEmpty = true,
}: Props) {
  const listId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlight, setHighlight] = useState(0);

  const selected = useMemo(
    () => options.find((o) => o.value === value) || null,
    [options, value]
  );

  const filtered = useMemo(() => {
    const list = options.filter((o) => matchesQuery(o, query));
    return list;
  }, [options, query]);

  useEffect(() => {
    if (!open) return;
    setHighlight(0);
  }, [query, open]);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) {
        setOpen(false);
        setQuery("");
      }
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  function openList() {
    if (disabled) return;
    setOpen(true);
    setQuery("");
    window.setTimeout(() => inputRef.current?.focus(), 0);
  }

  function pick(v: string) {
    onChange(v);
    setOpen(false);
    setQuery("");
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (!open) {
      if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openList();
      }
      return;
    }
    const rows = allowEmpty ? filtered.length + 1 : filtered.length;
    if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
      setQuery("");
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => (h + 1) % Math.max(rows, 1));
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => (h - 1 + Math.max(rows, 1)) % Math.max(rows, 1));
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      if (allowEmpty && highlight === 0) {
        pick("");
        return;
      }
      const idx = allowEmpty ? highlight - 1 : highlight;
      const opt = filtered[idx];
      if (opt) pick(opt.value);
    }
  }

  const display = open ? query : selected?.label || (value ? value : "");

  return (
    <div className={`search-select${open ? " open" : ""}${disabled ? " disabled" : ""}`} ref={rootRef}>
      <div className="search-select-control" onClick={openList}>
        <input
          ref={inputRef}
          type="text"
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          disabled={disabled}
          placeholder={selected ? selected.label : placeholder}
          value={display}
          onChange={(e) => {
            setQuery(e.target.value);
            if (!open) setOpen(true);
          }}
          onFocus={() => {
            if (!disabled) {
              setOpen(true);
              setQuery("");
            }
          }}
          onKeyDown={onKeyDown}
          autoComplete="off"
          spellCheck={false}
        />
        <span className="search-select-caret" aria-hidden>
          ▾
        </span>
      </div>
      {open && !disabled && (
        <ul id={listId} className="search-select-list" role="listbox">
          {allowEmpty && (
            <li
              role="option"
              aria-selected={!value}
              className={highlight === 0 ? "active" : ""}
              onMouseEnter={() => setHighlight(0)}
              onMouseDown={(e) => {
                e.preventDefault();
                pick("");
              }}
            >
              {emptyLabel}
            </li>
          )}
          {filtered.length === 0 && (
            <li className="muted empty">Sin coincidencias para “{query}”</li>
          )}
          {filtered.map((o, i) => {
            const hi = allowEmpty ? i + 1 : i;
            return (
              <li
                key={o.value}
                role="option"
                aria-selected={o.value === value}
                className={`${o.value === value ? "selected" : ""}${highlight === hi ? " active" : ""}`}
                onMouseEnter={() => setHighlight(hi)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(o.value);
                }}
              >
                {o.label}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

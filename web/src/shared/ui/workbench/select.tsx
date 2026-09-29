import { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown } from 'lucide-react';

export type SelectOption<T extends string = string> = {
  value: T;
  label: string;
};

export function WorkbenchSelect<T extends string>({
  'aria-label': ariaLabel,
  value,
  onChange,
  options,
  className,
  buttonClassName,
  testId,
  name,
}: {
  'aria-label': string;
  value: T;
  onChange: (value: T) => void;
  options: SelectOption<T>[];
  className?: string;
  buttonClassName?: string;
  testId?: string;
  name?: string;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const selectedOption =
    options.find((opt) => opt.value === value) ?? options[0];
  const displayLabel = selectedOption?.label ?? value;

  useEffect(() => {
    if (!isOpen) return;
    function handleClickOutside(event: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setIsOpen(false);
      }
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen]);

  return (
    <div
      ref={containerRef}
      className={`relative inline-block ${className ?? ''}`.trim()}
    >
      <select
        aria-label={ariaLabel}
        data-testid={testId}
        name={name}
        value={value}
        onChange={(event) => onChange(event.target.value as T)}
        className="sr-only"
        tabIndex={-1}
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      <button
        type="button"
        onClick={() => setIsOpen((prev) => !prev)}
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        className={`app-field inline-flex h-10 items-center justify-between gap-1.5 rounded-[var(--app-radius-control)] pl-2.5 pr-2 text-xs sm:h-8 cursor-pointer bg-[var(--app-surface-raised)] text-[var(--app-text)] hover:border-[var(--app-border)] focus:border-[var(--app-focus-ring)] focus:outline-none ${buttonClassName ?? ''}`.trim()}
      >
        <span className="truncate">{displayLabel}</span>
        <ChevronDown
          size={13}
          className={`shrink-0 text-[var(--app-text-tertiary)] transition-transform duration-[var(--app-motion-fast)] ease-[var(--app-ease-standard)] ${
            isOpen ? 'rotate-180' : ''
          }`}
          aria-hidden="true"
        />
      </button>

      {isOpen ? (
        <div
          role="listbox"
          aria-label={ariaLabel}
          className="absolute left-0 top-full z-50 mt-1 min-w-full w-max max-w-xs rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface-raised)] p-1 shadow-lg"
        >
          {options.map((opt) => {
            const isSelected = opt.value === value;
            return (
              <button
                key={opt.value}
                type="button"
                role="option"
                aria-selected={isSelected}
                onClick={() => {
                  onChange(opt.value);
                  setIsOpen(false);
                }}
                className={`flex w-full items-center justify-between gap-2 rounded px-2 py-1.5 text-left text-xs transition-colors cursor-pointer ${
                  isSelected
                    ? 'bg-[var(--app-accent-bg)] font-semibold text-[var(--app-accent)]'
                    : 'text-[var(--app-text)] hover:bg-[var(--app-surface)]'
                }`}
              >
                <span className="truncate">{opt.label}</span>
                {isSelected ? (
                  <Check
                    size={13}
                    className="shrink-0 text-[var(--app-accent)]"
                    aria-hidden="true"
                  />
                ) : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

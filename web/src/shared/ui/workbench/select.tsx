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
  return (
    <div className={`relative inline-block min-w-0 ${className ?? ''}`.trim()}>
      <select
        aria-label={ariaLabel}
        data-testid={testId}
        name={name}
        value={value}
        onChange={(event) => onChange(event.target.value as T)}
        className={`app-field h-10 max-w-full cursor-pointer appearance-none rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)] pl-2.5 text-xs text-[var(--app-text)] hover:border-[var(--app-border)] focus:border-[var(--app-focus-ring)] focus:outline-none sm:h-8 ${buttonClassName ?? ''}`.trim()}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

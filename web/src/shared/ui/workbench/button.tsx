import type { ButtonHTMLAttributes } from 'react';

import { cn } from '../../utils/cn';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
export type ButtonSize = 'xs' | 'sm' | 'md';

export function Button({
  variant = 'secondary',
  size = 'sm',
  className,
  type = 'button',
  loading,
  disabled,
  'aria-busy': ariaBusy,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
}) {
  const isBusy = Boolean(loading || ariaBusy);
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={isBusy ? 'true' : undefined}
      data-loading={loading ? 'true' : undefined}
      data-workbench-primitive="button"
      data-button-variant={variant}
      data-button-size={size}
      className={cn(
        'app-button',
        'app-button-' + variant,
        'app-button-' + size,
        className,
      )}
      {...props}
    />
  );
}

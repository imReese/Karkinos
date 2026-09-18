import type { ButtonHTMLAttributes } from 'react';

import { cn } from '../../utils/cn';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
export type ButtonSize = 'xs' | 'sm' | 'md';

export function Button({
  variant = 'secondary',
  size = 'sm',
  className,
  type = 'button',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
}) {
  return (
    <button
      type={type}
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

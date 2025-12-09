import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { clsx } from 'clsx';

interface GradientButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon?: ReactNode;
  label?: string;
  busy?: boolean;
  busyLabel?: string;
}

export function GradientButton({
  icon,
  label,
  busy,
  busyLabel = 'Bitte warten …',
  className,
  children,
  disabled,
  ...props
}: GradientButtonProps) {
  return (
    <button
      className={clsx('gradient-button', className)}
      disabled={disabled || busy}
      {...props}
    >
      {busy ? (
        <span>{busyLabel}</span>
      ) : (
        <>
          {icon}
          {label && <span>{label}</span>}
          {children}
        </>
      )}
    </button>
  );
}

export default GradientButton;

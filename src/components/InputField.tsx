import type { InputHTMLAttributes, ReactNode } from 'react';
import { clsx } from 'clsx';

interface InputFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  hint?: string;
  trailing?: ReactNode;
}

export function InputField({
  label,
  hint,
  trailing,
  className,
  ...props
}: InputFieldProps) {
  return (
    <div className={clsx('form-field', className)}>
      <label>{label}</label>
      <div style={{ position: 'relative' }}>
        <input className="input-control" {...props} />
        {trailing && (
          <span
            style={{
              position: 'absolute',
              right: 12,
              top: '50%',
              transform: 'translateY(-50%)',
            }}
          >
            {trailing}
          </span>
        )}
      </div>
      {hint && (
        <small style={{ color: 'var(--text-secondary)' }}>{hint}</small>
      )}
    </div>
  );
}

export default InputField;

import type { ReactNode } from 'react';

interface AuthLayoutProps {
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
}

export function AuthLayout({ title, subtitle, children, footer }: AuthLayoutProps) {
  return (
    <div className="auth-layout">
      <div className="glass-panel auth-card">
        <div className="auth-card__header">
          <p className="chip" style={{ width: 'fit-content' }}>
            Drawform AI
          </p>
          <h1>{title}</h1>
          {subtitle && <p>{subtitle}</p>}
        </div>
        <div className="stack">{children}</div>
        {footer && <div className="auth-card__footer">{footer}</div>}
      </div>
    </div>
  );
}

export default AuthLayout;

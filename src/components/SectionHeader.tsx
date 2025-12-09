import type { ReactNode } from 'react';

interface SectionHeaderProps {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}

export function SectionHeader({ title, subtitle, action }: SectionHeaderProps) {
  return (
    <div className="section-header">
      <div>
        <h2>{title}</h2>
        {subtitle && <span>{subtitle}</span>}
      </div>
      {action}
    </div>
  );
}

export default SectionHeader;

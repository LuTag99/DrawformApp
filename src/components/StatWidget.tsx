import type { ReactNode } from 'react';
import { motion } from 'framer-motion';

interface StatWidgetProps {
  title: string;
  value: string;
  trendLabel: string;
  positive?: boolean;
  icon: ReactNode;
}

export function StatWidget({
  title,
  value,
  trendLabel,
  positive = true,
  icon,
}: StatWidgetProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="glass-panel"
      style={{
        padding: '1.5rem',
        minWidth: '240px',
        flex: '1 1 240px',
      }}
    >
      <div
        style={{
          width: 48,
          height: 48,
          borderRadius: 16,
          background: 'var(--gradient-accent)',
          display: 'grid',
          placeItems: 'center',
          color: '#fff',
          marginBottom: '1.25rem',
        }}
      >
        {icon}
      </div>
      <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
        {title}
      </span>
      <div
        style={{
          fontWeight: 600,
          fontSize: '2rem',
          marginTop: '0.2rem',
          marginBottom: '0.85rem',
        }}
      >
        {value}
      </div>
      <div
        className="chip"
        style={{
          color: positive ? '#22c55e' : '#f87171',
          borderColor: positive ? 'rgba(34,197,94,0.35)' : 'rgba(248,113,113,0.35)',
        }}
      >
        <span
          style={{
            display: 'inline-flex',
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: positive ? '#22c55e' : '#f87171',
          }}
        />
        {trendLabel}
      </div>
    </motion.div>
  );
}

export default StatWidget;

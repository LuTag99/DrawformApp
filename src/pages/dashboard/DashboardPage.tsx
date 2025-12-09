import { useEffect, useState } from 'react';
import {
  HiOutlineSparkles,
  HiOutlineFolder,
  HiOutlineClock,
} from 'react-icons/hi2';
import SectionHeader from '../../components/SectionHeader';
import { GradientButton } from '../../components/GradientButton';
import { StatWidget } from '../../components/StatWidget';
import { fetchAiInsight, type AiInsight } from '../../services/aiService';

const summary =
  '3 Projekte aktiv, Exportquote stabil bei 0% Fehlern. Letzter Export vor 2 Tagen.';

export function DashboardPage() {
  const [insight, setInsight] = useState<AiInsight>({
    narrative: 'Die KI beobachtet stabile Pipelines. Nutze freie Kapazität!',
    chips: ['0% Fehler', 'AI Quality', 'Glas UI'],
  });
  const [busy, setBusy] = useState(false);

  const refreshInsight = async () => {
    setBusy(true);
    const result = await fetchAiInsight(summary);
    setInsight(result);
    setBusy(false);
  };

  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      void refreshInsight();
    });
    return () => cancelAnimationFrame(frame);
  }, []);

  return (
    <div className="stack">
      <div className="glass-panel shell-card">
        <SectionHeader
          title="Dashboard"
          subtitle="Glass look, AI Insights & Exportleistung auf einen Blick."
        />
        <div className="stat-grid" style={{ marginTop: '1.5rem' }}>
          <StatWidget
            title="Aktive Projekte"
            value="3"
            trendLabel="+12% Woche"
            positive
            icon={<HiOutlineFolder />}
          />
          <StatWidget
            title="Letzter Export"
            value="48h"
            trendLabel="Stabilität bestätigt"
            positive
            icon={<HiOutlineClock />}
          />
          <StatWidget
            title="AI Qualität"
            value="0% Fehler"
            trendLabel="Keine Abweichungen"
            positive
            icon={<HiOutlineSparkles />}
          />
        </div>
      </div>
      <div className="glass-panel shell-card">
        <SectionHeader
          title="AI Insights"
          subtitle="GPT-gestützte Empfehlungen für Exportpipelines."
          action={
            <GradientButton
              onClick={refreshInsight}
              label="Insights aktualisieren"
              busy={busy}
              busyLabel="KI analysiert …"
            />
          }
        />
        <p style={{ color: 'var(--text-secondary)', marginTop: '1rem' }}>
          {insight.narrative}
        </p>
        <div className="ai-chip-group">
          {insight.chips.map((chip) => (
            <span key={chip} className="chip">
              <HiOutlineSparkles /> {chip}
            </span>
          ))}
        </div>
        <div className="chart-shell">
          <InsightChart />
        </div>
      </div>
    </div>
  );
}

function InsightChart() {
  const points = [80, 56, 90, 40, 75, 35, 88];
  const width = 600;
  const height = 220;
  const path = points
    .map((point, index) => {
      const x = (index / (points.length - 1)) * width;
      const y = height - (point / 100) * height;
      return `${index === 0 ? 'M' : 'L'} ${x},${y}`;
    })
    .join(' ');

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" height="220">
      <defs>
        <linearGradient id="chartLine" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="#4f46e5" />
          <stop offset="50%" stopColor="#0ea5e9" />
          <stop offset="100%" stopColor="#a855f7" />
        </linearGradient>
        <linearGradient id="chartFill" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="rgba(79,70,229,0.35)" />
          <stop offset="100%" stopColor="rgba(79,70,229,0)" />
        </linearGradient>
      </defs>
      <path
        d={`${path} L ${width},${height} L 0,${height} Z`}
        fill="url(#chartFill)"
        stroke="none"
      />
      <path
        d={path}
        fill="none"
        stroke="url(#chartLine)"
        strokeWidth="4"
        strokeLinecap="round"
      />
    </svg>
  );
}

export default DashboardPage;

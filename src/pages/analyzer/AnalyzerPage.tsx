import { type ChangeEvent, type FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import {
  HiOutlineCloudArrowUp,
  HiOutlineClock,
  HiOutlineCheckCircle,
  HiOutlineSparkles,
  HiOutlineDocumentArrowDown,
  HiOutlineCubeTransparent,
} from 'react-icons/hi2';
import SectionHeader from '../../components/SectionHeader';
import { InputField } from '../../components/InputField';
import { GradientButton } from '../../components/GradientButton';
import { useAnalyzerJobs } from '../../hooks/useAnalyzerJobs';
import {
  type AnalyzerJob,
  type AnalyzerResult,
  type AnalyzerUnit,
  createAnalysisJob,
  fetchDimensions,
} from '../../services/analyzerService';

const viewOptions = ['Vorne', 'Oben', 'Seite', 'Iso', 'Abwicklung'];
const unitOptions: AnalyzerUnit[] = ['mm', 'cm', 'inch'];

export function AnalyzerPage() {
  const jobs = useAnalyzerJobs();
  const [selectedViews, setSelectedViews] = useState<string[]>(['Iso']);
  const [unit, setUnit] = useState<AnalyzerUnit>('mm');
  const [scale, setScale] = useState(1.0);
  const [layer, setLayer] = useState('AI_DIMENSIONS');
  const [notes, setNotes] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [filePreview, setFilePreview] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ type: 'success' | 'error'; message: string } | null>(
    null,
  );
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [pollBusy, setPollBusy] = useState(false);

  useEffect(() => {
    if (!jobs.length) {
      setActiveJobId(null);
      return;
    }
    if (!activeJobId || !jobs.some((job) => job.id === activeJobId)) {
      setActiveJobId(jobs[0].id);
    }
  }, [jobs, activeJobId]);

  const activeJob = useMemo(() => jobs.find((job) => job.id === activeJobId), [jobs, activeJobId]);

  useEffect(() => {
    return () => {
      if (filePreview) {
        URL.revokeObjectURL(filePreview);
      }
    };
  }, [filePreview]);

  const handleSelectFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    setSelectedFile(file ?? null);
    setStatus(null);
    if (file && file.type.startsWith('image/')) {
      if (filePreview) {
        URL.revokeObjectURL(filePreview);
      }
      setFilePreview(URL.createObjectURL(file));
    } else {
      if (filePreview) {
        URL.revokeObjectURL(filePreview);
      }
      setFilePreview(null);
    }
  };

  const toggleView = (view: string) => {
    setSelectedViews((previous) =>
      previous.includes(view)
        ? previous.filter((item) => item !== view)
        : [...previous, view],
    );
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedFile) {
      setStatus({
        type: 'error',
        message: 'Bitte zuerst ein Bild oder CAD-File importieren.',
      });
      return;
    }
    if (!selectedViews.length) {
      setStatus({ type: 'error', message: 'Mindestens eine Ansicht auswaehlen.' });
      return;
    }
    setBusy(true);
    try {
      const metadata = {
        units: unit,
        scale,
        layer: layer.trim() || 'AI_DIMENSIONS',
        notes: notes.trim() || undefined,
        views: selectedViews,
      };
      const job = await createAnalysisJob(selectedFile, metadata);
      setSelectedFile(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
      if (filePreview) {
        URL.revokeObjectURL(filePreview);
        setFilePreview(null);
      }
      setStatus({ type: 'success', message: 'Job an OpenAI-Worker gesendet.' });
      setActiveJobId(job.id);
    } catch (error) {
      setStatus({
        type: 'error',
        message: (error as Error)?.message ?? 'Unbekannter Fehler beim Analysieren.',
      });
    } finally {
      setBusy(false);
    }
  };

  const handlePollDimensions = async () => {
    if (!activeJobId) {
      return;
    }
    setPollBusy(true);
    try {
      const result = await fetchDimensions(activeJobId);
      if (result) {
        setStatus({ type: 'success', message: 'Aktuelle Bemassung geladen.' });
      } else {
        setStatus({ type: 'error', message: 'Job ist noch in Bearbeitung.' });
      }
    } catch (error) {
      setStatus({
        type: 'error',
        message: (error as Error)?.message ?? 'Dimensionen konnten nicht geladen werden.',
      });
    } finally {
      setPollBusy(false);
    }
  };

  return (
    <div className="stack">
      <div className="glass-panel shell-card">
        <SectionHeader
          title="Bemaessungslabor"
          subtitle="Client erstellt Views, Backend erzeugt Jobs und Worker liefern AI-Bemassungen."
        />
        <form onSubmit={handleSubmit} className="analysis-form">
          <div className="upload-tile" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: '1rem' }}>
            <div>
              <strong>{selectedFile?.name ?? 'Noch nichts importiert'}</strong>
              <p style={{ margin: '0.35rem 0 0', color: 'var(--text-secondary)' }}>
                PNG/JPEG sowie DXF, DWG, STEP, IGES. Wir erstellen automatisch Front-, Top-, Seiten-Views.
              </p>
            </div>
            <div style={{ display: 'flex', gap: '0.75rem', width: '100%', flexWrap: 'wrap' }}>
              <GradientButton
                type="button"
                icon={<HiOutlineCloudArrowUp />}
                label="View importieren"
                onClick={() => fileInputRef.current?.click()}
              />
              {selectedFile && (
                <span className="chip" style={{ background: 'rgba(15,23,42,0.6)' }}>
                  {formatBytes(selectedFile.size)} | {selectedFile.type || 'CAD'}
                </span>
              )}
              <input
                ref={fileInputRef}
                type="file"
                accept=".png,.jpg,.jpeg,.webp,.dxf,.dwg,.step,.iges,.stl"
                style={{ display: 'none' }}
                onChange={handleSelectFile}
              />
            </div>
            {filePreview && (
              <div className="analysis-preview">
                <img src={filePreview} alt="Preview" />
              </div>
            )}
          </div>
          <div>
            <p className="analysis-label">Ansichten</p>
            <div className="analysis-chip-row">
              {viewOptions.map((view) => (
                <button
                  key={view}
                  type="button"
                  className={selectedViews.includes(view) ? 'analysis-chip active' : 'analysis-chip'}
                  onClick={() => toggleView(view)}
                >
                  {view}
                </button>
              ))}
            </div>
          </div>
          <div className="analysis-meta">
            <div>
              <p className="analysis-label">Einheiten</p>
              <div className="analysis-chip-row">
                {unitOptions.map((item) => (
                  <button
                    key={item}
                    type="button"
                    className={unit === item ? 'analysis-chip active' : 'analysis-chip'}
                    onClick={() => setUnit(item)}
                  >
                    {item.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <p className="analysis-label">Skalierung</p>
              <div className="scale-control">
                <input
                  type="range"
                  min="1"
                  max="4"
                  step="0.1"
                  value={scale}
                  onChange={(event) => setScale(Number(event.target.value))}
                />
                <span>{scale.toFixed(1)}x</span>
              </div>
            </div>
            <InputField
              label="Layer"
              value={layer}
              onChange={(event) => setLayer(event.target.value)}
              placeholder="AI_DIMENSIONS"
            />
          </div>
          <label className="analysis-label" htmlFor="notes">
            Notizen fuer GPT
          </label>
          <textarea
            id="notes"
            className="input-control"
            rows={3}
            placeholder="z.B. Biegelinien priorisieren, ~10 Bohrung hervorheben"
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
          />
          <GradientButton
            type="submit"
            label="Analyse starten"
            icon={<HiOutlineSparkles />}
            busy={busy}
            busyLabel="Worker wird informiert..."
          />
          {status && (
            <div
              className={`status-banner ${
                status.type === 'success' ? 'status-banner--success' : 'status-banner--error'
              }`}
            >
              {status.message}
            </div>
          )}
        </form>
      </div>
      <div className="glass-panel shell-card">
        <SectionHeader
          title="Jobs & Dimensionen"
          subtitle="REST-Aufrufe simulieren /analyze & /dimensions - Worker verarbeitet via OpenAI."
          action={
            <GradientButton
              type="button"
              label="Dimensionen abrufen"
              icon={<HiOutlineDocumentArrowDown />}
              onClick={handlePollDimensions}
              busy={pollBusy}
              busyLabel="Frage Backend..."
            />
          }
        />
        <div className="job-grid">
          <div className="job-list">
            {jobs.length === 0 && (
              <div className="job-empty">
                <HiOutlineCubeTransparent size={32} />
                <p>Keine Jobs. Starte eine Analyse, damit der Worker loslegt.</p>
              </div>
            )}
            {jobs.map((job) => (
              <JobCard
                key={job.id}
                job={job}
                active={job.id === activeJobId}
                onSelect={() => setActiveJobId(job.id)}
              />
            ))}
          </div>
          <DimensionPreview job={activeJob} />
        </div>
      </div>
    </div>
  );
}

function JobCard({ job, active, onSelect }: { job: AnalyzerJob; active: boolean; onSelect: () => void }) {
  const statusCopy = {
    pending: 'Wartet auf Worker',
    processing: 'Verarbeitung',
    completed: 'Masse bereit',
    failed: 'Fehlgeschlagen',
  } as const;

  const createdLabel = useMemo(() => {
    try {
      return new Date(job.createdAt).toLocaleTimeString('de-DE', {
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return job.createdAt;
    }
  }, [job.createdAt]);

  return (
    <button type="button" className={active ? 'job-card active' : 'job-card'} onClick={onSelect}>
      <div className="job-card__header">
        <div>
          <strong>{job.fileName}</strong>
          <p>{formatBytes(job.size)}</p>
        </div>
        <span className={`job-card__status job-card__status--${job.status}`}>
          {statusCopy[job.status]}
        </span>
      </div>
      <div className="analysis-chip-row" style={{ marginTop: '0.65rem' }}>
        {job.metadata.views.map((view) => (
          <span key={view} className="chip" style={{ textTransform: 'uppercase', fontSize: '0.75rem' }}>
            {view}
          </span>
        ))}
      </div>
      <div className="job-card__footer">
        <span>
          <HiOutlineClock /> {createdLabel}
        </span>
        <span>
          <HiOutlineCloudArrowUp /> {job.metadata.layer}
        </span>
      </div>
    </button>
  );
}

function DimensionPreview({ job }: { job: AnalyzerJob | undefined }) {
  if (!job) {
    return (
      <div className="dimension-stage glass-panel--soft">
        <p style={{ color: 'var(--text-secondary)' }}>Waehle einen Job aus, um die Ergebnisse zu sehen.</p>
      </div>
    );
  }

  const orderedViews = ['Iso', 'Vorne', 'Oben', 'Seite', 'Abwicklung'];
  const views =
    job.metadata.views.length > 0
      ? orderedViews.filter((view) => job.metadata.views.includes(view))
      : ['Iso'];

  const statusLabel =
    job.status === 'completed'
      ? 'Dimensionen bereit'
      : job.status === 'processing'
        ? 'Worker rechnet'
        : job.status === 'pending'
          ? 'Eingang'
          : 'Fehler';

  return (
    <div className="dimension-sheet glass-panel--soft dimension-stage">
      <div className="dimension-sheet__header">
        <div>
          <strong>Fertigungszeichnung</strong>
          <p>
            {job.fileName} | Layer {job.metadata.layer} | {job.metadata.units.toUpperCase()} | {views.join(', ')}
          </p>
        </div>
        <span className={`job-card__status job-card__status--${job.status}`}>{statusLabel}</span>
      </div>
      {job.result ? (
        <>
          <div className="dimension-meta">
            <div>
              <span>Confidence</span>
              <strong>{job.result.confidence}%</strong>
            </div>
            <div>
              <span>Modell</span>
              <strong>{job.result.modelVersion}</strong>
            </div>
            <div>
              <span>Abgeschlossen</span>
              <strong>{new Date(job.result.completedAt).toLocaleTimeString('de-DE')}</strong>
            </div>
          </div>
          <div className="drawing-view-grid">
            {views.map((view) => (
              <DrawingView key={view} job={job} view={view} />
            ))}
          </div>
          <div className="dimension-sheet__bottom">
            <div className="dimension-sheet__details">
              <p style={{ margin: '0 0 0.6rem', color: 'var(--text-secondary)' }}>{job.result.summary}</p>
              <Measurements result={job.result} />
              <Recommendations items={job.result.recommendations} />
            </div>
            <TitleBlockPlaceholder job={job} />
          </div>
        </>
      ) : (
        <p style={{ color: 'var(--text-secondary)' }}>
          {job.status === 'failed'
            ? 'Worker meldet einen Fehler. Bitte erneut exportieren.'
            : 'Worker verarbeitet den Auftrag. Sobald Vision & GPT fertig sind, erscheinen hier die Abmessungen.'}
        </p>
      )}
    </div>
  );
}

function DrawingView({ job, view }: { job: AnalyzerJob; view: string }) {
  const hasPreview = !!job.preview && (job.sourceType === 'image' || view.toLowerCase() === 'iso');

  return (
    <div className="drawing-view">
      <div className="drawing-view__title">
        <span>{view}</span>
        <span className="chip chip--ghost">
          1:{job.metadata.scale.toFixed(1)} | {job.metadata.units.toUpperCase()}
        </span>
      </div>
      <div className="drawing-view__canvas">
        {hasPreview ? (
          <img src={job.preview} alt={`${view} Preview`} />
        ) : (
          <div className="drawing-view__placeholder">
            <HiOutlineCubeTransparent size={32} />
            <span>Keine Vorschau fuer {view}</span>
          </div>
        )}
        {job.result && <DimensionOverlaySvg job={job} />}
      </div>
    </div>
  );
}

function Measurements({ result }: { result: AnalyzerResult }) {
  return (
    <div className="dimension-measurements">
      {result.measurements.map((measurement) => (
        <div key={measurement.id} className="dimension-chip">
          <div>
            <strong>{measurement.label}</strong>
            <p>
              {measurement.value} {measurement.unit}
            </p>
          </div>
          <div>
            <span>{measurement.tolerance}</span>
            <small>{measurement.explanation}</small>
          </div>
        </div>
      ))}
    </div>
  );
}

function Recommendations({ items }: { items: string[] }) {
  return (
    <div className="recommendation-list">
      {items.map((item) => (
        <span key={item}>
          <HiOutlineCheckCircle /> {item}
        </span>
      ))}
    </div>
  );
}

function TitleBlockPlaceholder({ job }: { job: AnalyzerJob }) {
  const completed =
    job.result?.completedAt && !Number.isNaN(Date.parse(job.result.completedAt))
      ? new Date(job.result.completedAt).toLocaleDateString('de-DE')
      : '-';

  return (
    <div className="title-block">
      <div className="title-block__header">Schriftfeld (Platzhalter)</div>
      <div className="title-block__grid">
        <TitleBlockRow label="Projekt" value={job.fileName} />
        <TitleBlockRow label="Layer" value={job.metadata.layer} />
        <TitleBlockRow label="Einheiten" value={job.metadata.units.toUpperCase()} />
        <TitleBlockRow label="Skalierung" value={`1:${job.metadata.scale.toFixed(1)}`} />
        <TitleBlockRow label="Status" value={job.status.toUpperCase()} />
        <TitleBlockRow label="Fertig" value={completed} />
        <TitleBlockRow label="Gezeichnet von" value="AI Worker" />
        <TitleBlockRow label="Geprueft" value="N/A" />
      </div>
    </div>
  );
}

function TitleBlockRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="title-block__row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function DimensionOverlaySvg({ job }: { job: AnalyzerJob }) {
  if (!job.result) {
    return null;
  }
  return (
    <svg className="dimension-overlay" viewBox="0 0 100 100" preserveAspectRatio="none">
      {job.result.overlays.map((overlay) => {
        const measurement = job.result?.measurements.find((item) => item.id === overlay.measurementId);
        const label = measurement ? `${measurement.label} - ${measurement.value} ${measurement.unit}` : overlay.measurementId;
        return (
          <g key={overlay.id} className={`dimension-overlay__line dimension-overlay__line--${overlay.axis}`}>
            <line x1={overlay.start.x * 100} y1={overlay.start.y * 100} x2={overlay.end.x * 100} y2={overlay.end.y * 100} />
            <text x={(overlay.start.x + overlay.end.x) * 50} y={(overlay.start.y + overlay.end.y) * 50}>
              {label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes)) {
    return '';
  }
  if (bytes === 0) {
    return '0 B';
  }
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / k ** i).toFixed(1)} ${sizes[i]}`;
}

export default AnalyzerPage;

import { type ChangeEvent, type FormEvent, useRef, useState } from 'react';
import {
  HiOutlineCloudArrowUp,
  HiOutlineCube,
  HiOutlineCheckCircle,
  HiOutlineExclamationCircle,
  HiOutlineClock,
  HiOutlineArrowDownTray,
  HiOutlineInformationCircle,
} from 'react-icons/hi2';
import SectionHeader from '../../components/SectionHeader';
import { GradientButton } from '../../components/GradientButton';
import { useReconstructJobs } from '../../hooks/useReconstructJobs';
import {
  type ReconstructJob,
  createReconstructJob,
  downloadReconstructFile,
} from '../../services/reconstructService';

// --------------------------------------------------------------------------
// Typen & Konstanten
// --------------------------------------------------------------------------

type ViewKey = 'front' | 'top' | 'left' | 'right' | 'back';

const VIEW_LABELS: Record<ViewKey, string> = {
  front: 'Vorne',
  top: 'Oben',
  left: 'Links',
  right: 'Rechts',
  back: 'Hinten',
};

const VIEW_KEYS: ViewKey[] = ['front', 'top', 'left', 'right', 'back'];

// --------------------------------------------------------------------------
// Hilfsfunktionen
// --------------------------------------------------------------------------


function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString('de-DE', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

function StatusIcon({ status }: { status: ReconstructJob['status'] }) {
  if (status === 'completed') {
    return <HiOutlineCheckCircle style={{ color: 'var(--color-success, #22c55e)', fontSize: '1.2rem' }} />;
  }
  if (status === 'failed') {
    return <HiOutlineExclamationCircle style={{ color: 'var(--color-danger, #ef4444)', fontSize: '1.2rem' }} />;
  }
  return <HiOutlineClock style={{ color: 'var(--text-secondary)', fontSize: '1.2rem', animation: 'spin 2s linear infinite' }} />;
}

// --------------------------------------------------------------------------
// Foto-Upload-Feld für eine Ansicht
// --------------------------------------------------------------------------

interface PhotoFieldProps {
  label: string;
  file: File | null;
  preview: string | null;
  onChange: (file: File | null) => void;
}

function PhotoField({ label, file, preview, onChange }: PhotoFieldProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  const handleChange = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] ?? null;
    onChange(f);
  };

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: '0.5rem',
        width: '100%',
      }}
    >
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        style={{
          width: '100%',
          aspectRatio: '1',
          background: preview
            ? `url(${preview}) center/cover no-repeat`
            : 'rgba(255,255,255,0.04)',
          border: file ? '1.5px solid rgba(139,92,246,0.6)' : '1.5px dashed rgba(255,255,255,0.15)',
          borderRadius: '10px',
          cursor: 'pointer',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '0.4rem',
          color: 'var(--text-secondary)',
          fontSize: '0.75rem',
          transition: 'border-color 0.2s',
          overflow: 'hidden',
        }}
        aria-label={`${label} Foto hochladen`}
      >
        {!preview && (
          <>
            <HiOutlineCloudArrowUp style={{ fontSize: '1.5rem', opacity: 0.5 }} />
            <span>Foto</span>
          </>
        )}
      </button>
      <span
        style={{
          fontSize: '0.75rem',
          fontWeight: 600,
          color: file ? 'rgba(139,92,246,0.9)' : 'var(--text-secondary)',
          letterSpacing: '0.05em',
        }}
      >
        {label}
      </span>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        style={{ display: 'none' }}
        onChange={handleChange}
      />
    </div>
  );
}

// --------------------------------------------------------------------------
// Job-Karte
// --------------------------------------------------------------------------

function JobCard({ job }: { job: ReconstructJob }) {
  const isActive = job.status === 'pending' || job.status === 'processing';

  return (
    <div
      style={{
        background: 'rgba(255,255,255,0.04)',
        border: '1px solid rgba(255,255,255,0.08)',
        borderRadius: '12px',
        padding: '1rem 1.25rem',
        display: 'flex',
        flexDirection: 'column',
        gap: '0.6rem',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
        <StatusIcon status={job.status} />
        <strong style={{ fontSize: '0.9rem' }}>{job.partName}</strong>
        <span
          style={{
            marginLeft: 'auto',
            fontSize: '0.75rem',
            color: 'var(--text-secondary)',
          }}
        >
          {formatDate(job.createdAt)}
        </span>
      </div>

      {isActive && job.progress && (
        <p style={{ margin: 0, fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
          {job.progress}
        </p>
      )}

      {job.status === 'failed' && job.error && (
        <p style={{ margin: 0, fontSize: '0.8rem', color: 'var(--color-danger, #ef4444)' }}>
          {job.error}
        </p>
      )}

      {job.result && job.status === 'completed' && (
        <>
          <div
            style={{
              display: 'flex',
              gap: '0.5rem',
              flexWrap: 'wrap',
              fontSize: '0.78rem',
              color: 'var(--text-secondary)',
            }}
          >
            <span>
              {job.result.dimensions_mm.width} ×{' '}
              {job.result.dimensions_mm.height} ×{' '}
              {job.result.dimensions_mm.depth} mm
            </span>
            <span>·</span>
            <span>{job.result.triangle_count.toLocaleString()} Dreiecke</span>
            <span>·</span>
            <span>
              Füllung: {(job.result.filled_voxel_ratio * 100).toFixed(1)}%
            </span>
          </div>

          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            {job.result.stl_available && (
              <button
                type="button"
                className="chip"
                onClick={() => downloadReconstructFile(job.id, 'stl')}
                style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.3rem' }}
              >
                <HiOutlineArrowDownTray /> STL
              </button>
            )}
            {job.result.step_available && (
              <button
                type="button"
                className="chip"
                onClick={() => downloadReconstructFile(job.id, 'step')}
                style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.3rem' }}
              >
                <HiOutlineArrowDownTray /> STEP
              </button>
            )}
            {job.result.pdf_available && (
              <button
                type="button"
                className="chip"
                onClick={() => downloadReconstructFile(job.id, 'pdf')}
                style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.3rem' }}
              >
                <HiOutlineArrowDownTray /> Zeichnung PDF
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
// Hauptseite
// --------------------------------------------------------------------------

export function ReconstructPage() {
  const jobs = useReconstructJobs();

  const [files, setFiles] = useState<Partial<Record<ViewKey, File>>>({});
  const [previews, setPreviews] = useState<Partial<Record<ViewKey, string>>>({});
  const [partName, setPartName] = useState('');
  const [widthMm, setWidthMm] = useState('');
  const [heightMm, setHeightMm] = useState('');
  const [depthMm, setDepthMm] = useState('');
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ type: 'success' | 'error'; message: string } | null>(
    null,
  );

  const handleFileChange = (view: ViewKey, file: File | null) => {
    setFiles((prev) => {
      const next = { ...prev };
      if (file) {
        next[view] = file;
      } else {
        delete next[view];
      }
      return next;
    });
    // Preview
    if (previews[view]) {
      URL.revokeObjectURL(previews[view]!);
    }
    setPreviews((prev) => {
      const next = { ...prev };
      if (file) {
        next[view] = URL.createObjectURL(file);
      } else {
        delete next[view];
      }
      return next;
    });
    setStatus(null);
  };

  const missingViews = VIEW_KEYS.filter((v) => !files[v]);
  const allPhotosUploaded = missingViews.length === 0;

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!allPhotosUploaded) {
      setStatus({
        type: 'error',
        message: `Fehlende Fotos: ${missingViews.map((v) => VIEW_LABELS[v]).join(', ')}`,
      });
      return;
    }
    setBusy(true);
    setStatus(null);
    try {
      await createReconstructJob({
        front: files.front!,
        top: files.top!,
        left: files.left!,
        right: files.right!,
        back: files.back!,
        partName: partName.trim() || 'Bauteil',
        widthMm: Math.max(1, parseFloat(widthMm) || 100),
        heightMm: Math.max(1, parseFloat(heightMm) || 100),
        depthMm: Math.max(1, parseFloat(depthMm) || 100),
      });
      // Felder zurücksetzen
      VIEW_KEYS.forEach((v) => {
        if (previews[v]) URL.revokeObjectURL(previews[v]!);
      });
      setFiles({});
      setPreviews({});
      setPartName('');
      setWidthMm('');
      setHeightMm('');
      setDepthMm('');
      setStatus({ type: 'success', message: 'Rekonstruktions-Job gestartet.' });
    } catch (error) {
      setStatus({
        type: 'error',
        message: (error as Error)?.message ?? 'Unbekannter Fehler',
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      {/* Formular */}
      <div className="glass-panel shell-card">
        <SectionHeader
          title="Foto → 3D-Modell"
          subtitle="5 Fotos aus festen Richtungen → STL → STEP → Technische Zeichnung"
        />

        {/* Hinweis-Banner */}
        <div
          style={{
            display: 'flex',
            gap: '0.6rem',
            alignItems: 'flex-start',
            background: 'rgba(139,92,246,0.08)',
            border: '1px solid rgba(139,92,246,0.2)',
            borderRadius: '8px',
            padding: '0.75rem 1rem',
            marginBottom: '1.25rem',
            fontSize: '0.8rem',
            color: 'var(--text-secondary)',
            lineHeight: 1.5,
          }}
        >
          <HiOutlineInformationCircle
            style={{ fontSize: '1.1rem', flexShrink: 0, marginTop: '0.1rem', color: 'rgba(139,92,246,0.8)' }}
          />
          <div>
            <strong style={{ color: 'var(--text-primary)' }}>Tipps für beste Ergebnisse:</strong>
            {' '}einfarbiger Hintergrund, gleichmäßiges Licht, Bauteil mittig und ohne Verdeckung.
            <br />
            Das erzeugte STEP-Modell enthält <strong>tessellierte Flächen</strong> — keine
            parametrischen CAD-Features. Geeignet für Maßreferenz und Import in CAD.
          </div>
        </div>

        <form onSubmit={handleSubmit} className="analysis-form">
          {/* 5 Foto-Felder */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(5, 1fr)',
              gap: '0.75rem',
              marginBottom: '1.25rem',
            }}
          >
            {VIEW_KEYS.map((view) => (
              <PhotoField
                key={view}
                label={VIEW_LABELS[view]}
                file={files[view] ?? null}
                preview={previews[view] ?? null}
                onChange={(f) => handleFileChange(view, f)}
              />
            ))}
          </div>

          {/* Dimensionen + Bauteilname */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
              gap: '0.75rem',
              marginBottom: '1.25rem',
            }}
          >
            <div>
              <label
                style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'block', marginBottom: '0.3rem' }}
              >
                Bauteilname
              </label>
              <input
                type="text"
                className="input-field"
                placeholder="z.B. Halteblech"
                value={partName}
                onChange={(e) => setPartName(e.target.value)}
                maxLength={80}
              />
            </div>
            <div>
              <label
                style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'block', marginBottom: '0.3rem' }}
              >
                Breite (mm)
              </label>
              <input
                type="number"
                className="input-field"
                placeholder="100"
                value={widthMm}
                onChange={(e) => setWidthMm(e.target.value)}
                min={1}
                max={10000}
              />
            </div>
            <div>
              <label
                style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'block', marginBottom: '0.3rem' }}
              >
                Höhe (mm)
              </label>
              <input
                type="number"
                className="input-field"
                placeholder="100"
                value={heightMm}
                onChange={(e) => setHeightMm(e.target.value)}
                min={1}
                max={10000}
              />
            </div>
            <div>
              <label
                style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'block', marginBottom: '0.3rem' }}
              >
                Tiefe (mm)
              </label>
              <input
                type="number"
                className="input-field"
                placeholder="100"
                value={depthMm}
                onChange={(e) => setDepthMm(e.target.value)}
                min={1}
                max={10000}
              />
            </div>
          </div>

          {/* Status-Banner */}
          {status && (
            <div
              className={`status-banner status-banner--${status.type}`}
              style={{ marginBottom: '1rem' }}
            >
              {status.message}
            </div>
          )}

          {/* Fortschrittsanzeige fehlender Fotos */}
          {!allPhotosUploaded && (
            <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: '0.75rem' }}>
              Noch fehlend:{' '}
              {missingViews.map((v) => VIEW_LABELS[v]).join(', ')}
            </p>
          )}

          <GradientButton
            type="submit"
            icon={<HiOutlineCube />}
            label={busy ? 'Rekonstruktion läuft...' : 'Jetzt rekonstruieren'}
            disabled={busy || !allPhotosUploaded}
          />
        </form>
      </div>

      {/* Job-Liste */}
      {jobs.length > 0 && (
        <div className="glass-panel shell-card">
          <SectionHeader
            title="Rekonstruktions-Jobs"
            subtitle="Laufende und abgeschlossene Rekonstruktionen"
          />
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {jobs.map((job) => (
              <JobCard key={job.id} job={job} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default ReconstructPage;

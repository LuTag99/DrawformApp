import { type FormEvent, useRef, useState } from 'react';
import { HiOutlineArrowUpTray } from 'react-icons/hi2';
import SectionHeader from '../../components/SectionHeader';
import { GradientButton } from '../../components/GradientButton';
import { requestVectorExport } from '../../services/exportService';

const formats = ['dxf', 'dwg', 'svg', 'pdf'];

export function ExportPage() {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [format, setFormat] = useState('dxf');
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  const onSelectFile = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    setSelectedFile(file ?? null);
    setStatus(null);
  };

  const handleExport = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedFile) {
      setStatus({ type: 'error', message: 'Bitte zuerst eine Datei wählen.' });
      return;
    }
    setBusy(true);
    try {
      const result = await requestVectorExport(selectedFile, format);
      setStatus({
        type: result.success ? 'success' : 'error',
        message: result.path ? `${result.message} · Pfad: ${result.path}` : result.message,
      });
    } catch (error) {
      setStatus({
        type: 'error',
        message: (error as Error)?.message ?? 'Unbekannter Fehler beim Export.',
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="glass-panel shell-card">
      <SectionHeader
        title="Exportcenter"
        subtitle="Wandle CAD-Modelle verlustfrei in Vektorformate – gleiche Server-Infrastruktur wie drawform.ai."
      />
      <form onSubmit={handleExport} className="stack" style={{ marginTop: '1.5rem' }}>
        <div className="form-field">
          <label>3D Modell</label>
          <div className="upload-tile">
            <div>
              <strong>{selectedFile?.name ?? 'Noch keine Datei gewählt'}</strong>
              <p style={{ margin: '0.35rem 0 0', color: 'var(--text-secondary)' }}>
                Unterstützte Formate: STL, OBJ, STEP, IGES
              </p>
            </div>
            <GradientButton
              type="button"
              label="Datei wählen"
              icon={<HiOutlineArrowUpTray />}
              onClick={onSelectFile}
            />
            <input
              ref={fileInputRef}
              type="file"
              accept=".stl,.obj,.step,.iges"
              style={{ display: 'none' }}
              onChange={handleFileChange}
            />
          </div>
        </div>
        <div className="form-field">
          <label>Zielformat</label>
          <div className="format-selector">
            {formats.map((item) => (
              <button
                key={item}
                type="button"
                className={`format-chip ${format === item ? 'active' : ''}`}
                onClick={() => setFormat(item)}
              >
                {item.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
        <GradientButton
          type="submit"
          label="Export starten"
          busy={busy}
          busyLabel="Export läuft …"
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
  );
}

export default ExportPage;

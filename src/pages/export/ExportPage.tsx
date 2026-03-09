import { type FormEvent, useEffect, useRef, useState } from 'react';
import { HiOutlineArrowUpTray } from 'react-icons/hi2';
import SectionHeader from '../../components/SectionHeader';
import { GradientButton } from '../../components/GradientButton';
import { requestPdfExport, requestDxfExport } from '../../services/exportService';

export function ExportPage() {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);
  const [downloadName, setDownloadName] = useState<string | null>(null);
  const [copyState, setCopyState] = useState<'idle' | 'success' | 'error'>('idle');
  const [showPreview, setShowPreview] = useState(false);
  const [showLog, setShowLog] = useState(false);
  const [logText, setLogText] = useState<string | null>(null);
  const [logBusy, setLogBusy] = useState(false);
  const [logCopyState, setLogCopyState] = useState<'idle' | 'success' | 'error'>('idle');
  const [dxfBusy, setDxfBusy] = useState(false);
  const [dxfUrl, setDxfUrl] = useState<string | null>(null);
  const [dxfName, setDxfName] = useState<string | null>(null);
  const [dxfStatus, setDxfStatus] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  useEffect(() => {
    return () => {
      if (downloadUrl) {
        URL.revokeObjectURL(downloadUrl);
      }
    };
  }, [downloadUrl]);

  useEffect(() => {
    return () => {
      if (dxfUrl) {
        URL.revokeObjectURL(dxfUrl);
      }
    };
  }, [dxfUrl]);

  const onSelectFile = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    setSelectedFile(file ?? null);
    setStatus(null);
    setDownloadName(null);
    setShowPreview(false);
    setShowLog(false);
    setLogText(null);
    setDownloadUrl((current) => {
      if (current) {
        URL.revokeObjectURL(current);
      }
      return null;
    });
    setDxfUrl((current) => {
      if (current) {
        URL.revokeObjectURL(current);
      }
      return null;
    });
    setDxfName(null);
    setDxfStatus(null);
  };

  const handleExport = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedFile) {
      setStatus({ type: 'error', message: 'Bitte zuerst eine STEP-Datei waehlen.' });
      return;
    }
    const extension = selectedFile.name.split('.').pop()?.toLowerCase();
    if (!extension || !['step', 'stp'].includes(extension)) {
      setStatus({ type: 'error', message: 'Nur STEP-Dateien (.step/.stp) sind erlaubt.' });
      return;
    }
    setBusy(true);
    setDownloadName(null);
    setShowPreview(false);
    setShowLog(false);
    setLogText(null);
    setDownloadUrl((current) => {
      if (current) {
        URL.revokeObjectURL(current);
      }
      return null;
    });
    try {
      const result = await requestPdfExport(selectedFile);
      setStatus({
        type: result.success ? 'success' : 'error',
        message: result.message,
      });
      if (result.success && result.blobUrl) {
        setDownloadUrl(result.blobUrl);
        setDownloadName(result.fileName ?? 'drawing.pdf');
        setShowPreview(true);
      }
    } catch (error) {
      setStatus({
        type: 'error',
        message: (error as Error)?.message ?? 'Unbekannter Fehler beim Export.',
      });
    } finally {
      setBusy(false);
    }
  };

  const handleDxfExport = async () => {
    if (!selectedFile) return;
    setDxfBusy(true);
    setDxfStatus(null);
    setDxfUrl((current) => {
      if (current) URL.revokeObjectURL(current);
      return null;
    });
    try {
      const result = await requestDxfExport(selectedFile);
      setDxfStatus({ type: result.success ? 'success' : 'error', message: result.message });
      if (result.success && result.blobUrl) {
        setDxfUrl(result.blobUrl);
        setDxfName(result.fileName ?? 'flat_pattern.dxf');
      }
    } catch (error) {
      setDxfStatus({ type: 'error', message: (error as Error)?.message ?? 'DXF-Export fehlgeschlagen.' });
    } finally {
      setDxfBusy(false);
    }
  };

  const copyStatusMessage = async () => {
    if (!status?.message) {
      return;
    }
    setCopyState('idle');
    const message = status.message;
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(message);
        setCopyState('success');
        window.setTimeout(() => setCopyState('idle'), 1800);
        return;
      }
      throw new Error('Clipboard unavailable');
    } catch {
      const textarea = document.createElement('textarea');
      textarea.value = message;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();
      try {
        document.execCommand('copy');
        setCopyState('success');
        window.setTimeout(() => setCopyState('idle'), 1800);
      } catch {
        setCopyState('error');
        window.prompt('Fehlertext kopieren:', message);
        window.setTimeout(() => setCopyState('idle'), 1800);
      } finally {
        document.body.removeChild(textarea);
      }
    }
  };

  const toggleLog = async () => {
    const nextShow = !showLog;
    setShowLog(nextShow);
    if (!nextShow) {
      return;
    }
    if (logText || logBusy) {
      return;
    }
    setLogBusy(true);
    try {
      const response = await fetch('/api/logs/last');
      if (!response.ok) {
        const message = await response.text();
        setLogText(message || `Log nicht verfuegbar (${response.status}).`);
        return;
      }
      const text = await response.text();
      setLogText(text || 'Log ist leer.');
    } catch (error) {
      setLogText((error as Error)?.message ?? 'Log konnte nicht geladen werden.');
    } finally {
      setLogBusy(false);
    }
  };

  const copyLog = async () => {
    if (!logText) {
      return;
    }
    setLogCopyState('idle');
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(logText);
        setLogCopyState('success');
        window.setTimeout(() => setLogCopyState('idle'), 1800);
        return;
      }
      throw new Error('Clipboard unavailable');
    } catch {
      const textarea = document.createElement('textarea');
      textarea.value = logText;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();
      try {
        document.execCommand('copy');
        setLogCopyState('success');
        window.setTimeout(() => setLogCopyState('idle'), 1800);
      } catch {
        setLogCopyState('error');
        window.prompt('Log kopieren:', logText);
        window.setTimeout(() => setLogCopyState('idle'), 1800);
      } finally {
        document.body.removeChild(textarea);
      }
    }
  };

  return (
    <div className="glass-panel shell-card">
      <SectionHeader
        title="Exportcenter"
        subtitle="STEP zu 2D-Fertigungszeichnung: A3/A2 Auto, ISO 7200, mm."
      />
      <form onSubmit={handleExport} className="stack" style={{ marginTop: '1.5rem' }}>
        <div className="form-field">
          <label>STEP Modell</label>
          <div className="upload-tile">
            <div>
              <strong>{selectedFile?.name ?? 'Noch keine Datei gewaehlt'}</strong>
              <p style={{ margin: '0.35rem 0 0', color: 'var(--text-secondary)' }}>
                Unterstuetzte Formate: STEP (.step, .stp)
              </p>
            </div>
            <GradientButton
              type="button"
              label="Datei waehlen"
              icon={<HiOutlineArrowUpTray />}
              onClick={onSelectFile}
            />
            <input
              ref={fileInputRef}
              type="file"
              accept=".step,.stp"
              style={{ display: 'none' }}
              onChange={handleFileChange}
            />
          </div>
        </div>
        <div className="form-field">
          <label>Zielformat</label>
          <div className="format-selector">
            <button type="button" className="format-chip active" disabled>
              PDF (A3/A2 Auto)
            </button>
            <span className="chip chip--ghost">Top + Front + Left + Iso</span>
          </div>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
          <GradientButton type="submit" label="PDF erzeugen" busy={busy} busyLabel="Erzeuge PDF..." />
          <GradientButton
            type="button"
            label="DXF exportieren"
            busy={dxfBusy}
            busyLabel="Erzeuge DXF..."
            onClick={handleDxfExport}
          />
        </div>
        {downloadUrl && (
          <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
            <button type="button" className="gradient-button" onClick={() => setShowPreview((value) => !value)}>
              {showPreview ? 'Preview schliessen' : 'Preview anzeigen'}
            </button>
            <a className="gradient-button" href={downloadUrl} download={downloadName ?? 'drawing.pdf'}>
              PDF herunterladen
            </a>
          </div>
        )}
        {dxfUrl && (
          <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
            <a className="gradient-button" href={dxfUrl} download={dxfName ?? 'flat_pattern.dxf'}>
              DXF herunterladen
            </a>
          </div>
        )}
        {dxfStatus && dxfStatus.type === 'error' && (
          <div className="status-banner status-banner--error">
            <span style={{ flex: 1 }}>{dxfStatus.message}</span>
          </div>
        )}
        {status && (
          <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
            <button type="button" className="gradient-button" onClick={toggleLog} disabled={logBusy}>
              {logBusy ? 'Log laden...' : showLog ? 'Log schliessen' : 'Log anzeigen'}
            </button>
          </div>
        )}
        {downloadUrl && showPreview && (
          <div className="glass-panel--soft" style={{ padding: '1rem', borderRadius: 20 }}>
            <div
              style={{
                position: 'relative',
                width: '100%',
                aspectRatio: '420 / 297',
                borderRadius: 16,
                overflow: 'hidden',
                background: '#fff',
              }}
            >
              <iframe
                title="PDF Preview"
                src={downloadUrl}
                style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', border: 'none' }}
              />
            </div>
          </div>
        )}
        {showLog && (
          <div className="glass-panel--soft" style={{ padding: '1rem', borderRadius: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '0.5rem' }}>
              <button type="button" className="chip chip--ghost" onClick={copyLog} disabled={!logText}>
                {logCopyState === 'success'
                  ? 'Kopiert'
                  : logCopyState === 'error'
                    ? 'Kopie fehlgeschlagen'
                    : 'Log kopieren'}
              </button>
            </div>
            <pre
              style={{
                margin: 0,
                fontSize: 12,
                lineHeight: 1.5,
                whiteSpace: 'pre-wrap',
                maxHeight: 280,
                overflow: 'auto',
              }}
            >
              {logText ?? 'Log wird geladen...'}
            </pre>
          </div>
        )}
        {status && (
          <div
            className={`status-banner ${
              status.type === 'success' ? 'status-banner--success' : 'status-banner--error'
            }`}
          >
            <span style={{ flex: 1 }}>{status.message}</span>
            {status.type === 'error' && (
              <button type="button" className="chip chip--ghost" onClick={copyStatusMessage}>
                {copyState === 'success'
                  ? 'Kopiert'
                  : copyState === 'error'
                    ? 'Kopie fehlgeschlagen'
                    : 'Fehler kopieren'}
              </button>
            )}
          </div>
        )}
      </form>
    </div>
  );
}

export default ExportPage;

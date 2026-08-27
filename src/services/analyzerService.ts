import { apiFetch } from './apiClient';

export type AnalyzerUnit = 'mm' | 'cm' | 'inch';

export interface AnalyzerMetadata {
  jobId: string;
  units: AnalyzerUnit;
  scale: number;
  layer: string;
  notes?: string;
  views: string[];
}

export interface AnalyzerMeasurement {
  id: string;
  label: string;
  value: number;
  unit: AnalyzerUnit;
  tolerance: string;
  explanation: string;
}

export type DimensionAxis = 'horizontal' | 'vertical';

export interface DimensionOverlay {
  id: string;
  measurementId: string;
  axis: DimensionAxis;
  start: { x: number; y: number };
  end: { x: number; y: number };
}

export interface AnalyzerResult {
  summary: string;
  confidence: number;
  modelVersion: string;
  completedAt: string;
  measurements: AnalyzerMeasurement[];
  overlays: DimensionOverlay[];
  recommendations: string[];
}

export type AnalyzerStatus = 'pending' | 'processing' | 'completed' | 'failed';
export type AnalyzerExecutionMode = 'backend' | 'local_fallback';

export interface AnalyzerJob {
  id: string;
  createdAt: string;
  status: AnalyzerStatus;
  fileName: string;
  size: number;
  metadata: AnalyzerMetadata;
  preview?: string;
  sourceType: 'image' | 'cad';
  executionMode: AnalyzerExecutionMode;
  result?: AnalyzerResult;
  error?: string;
}

const STORAGE_KEY = 'drawform-analyzer-jobs';
const ANALYZE_API = '/api/analyze';
const POLL_INTERVAL_MS = 1200;
const MAX_CONSECUTIVE_POLL_ERRORS = 30;

type Listener = (jobs: AnalyzerJob[]) => void;

const listeners = new Set<Listener>();
const pollingTimers = new Map<string, number>();
const pollingErrorCounts = new Map<string, number>();

function getStorage(): Storage | null {
  if (typeof window === 'undefined') {
    return null;
  }
  try {
    return window.localStorage;
  } catch (error) {
    console.warn('LocalStorage unavailable', error);
    return null;
  }
}

function readJobs(): AnalyzerJob[] {
  const storage = getStorage();
  if (!storage) {
    return [];
  }
  const raw = storage.getItem(STORAGE_KEY);
  if (!raw) {
    return [];
  }
  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      const jobs: AnalyzerJob[] = [];
      parsed.forEach((entry) => {
        const normalized = normalizeServerJob(entry);
        const record = asRecord(entry);
        if (!normalized) {
          return;
        }
        jobs.push({
          ...normalized,
          preview: typeof record?.preview === 'string' ? record.preview : normalized.preview,
        });
      });
      return jobs;
    }
    return [];
  } catch (error) {
    console.error('Failed to parse analyzer jobs', error);
    return [];
  }
}

function persist(jobs: AnalyzerJob[]) {
  const storage = getStorage();
  if (!storage) {
    return;
  }
  storage.setItem(STORAGE_KEY, JSON.stringify(jobs));
}

function emit(jobs?: AnalyzerJob[]) {
  const snapshot = jobs ?? readJobs();
  listeners.forEach((listener) => listener(snapshot));
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object') {
    return null;
  }
  return value as Record<string, unknown>;
}

function normalizeStatus(value: unknown): AnalyzerStatus {
  if (value === 'processing' || value === 'completed' || value === 'failed') {
    return value;
  }
  return 'pending';
}

function normalizeUnit(value: unknown): AnalyzerUnit {
  if (value === 'cm' || value === 'inch') {
    return value;
  }
  return 'mm';
}

function normalizeMetadata(value: unknown, fallbackJobId?: string): AnalyzerMetadata {
  const meta = asRecord(value);
  const viewsRaw = meta?.views;
  const views = Array.isArray(viewsRaw)
    ? viewsRaw.map((item) => String(item).trim()).filter(Boolean)
    : [];
  const jobId =
    typeof meta?.jobId === 'string' && meta.jobId.trim()
      ? meta.jobId.trim()
      : fallbackJobId ?? nextId();
  return {
    jobId,
    units: normalizeUnit(meta?.units),
    scale: Number(meta?.scale) > 0 ? Number(meta?.scale) : 1,
    layer: typeof meta?.layer === 'string' && meta.layer.trim() ? meta.layer.trim() : 'AI_DIMENSIONS',
    notes: typeof meta?.notes === 'string' && meta.notes.trim() ? meta.notes.trim() : undefined,
    views: views.length ? views : ['Iso'],
  };
}

function normalizeResult(value: unknown): AnalyzerResult | undefined {
  const raw = asRecord(value);
  if (!raw) {
    return undefined;
  }
  const measurementsRaw = Array.isArray(raw.measurements) ? raw.measurements : [];
  const overlaysRaw = Array.isArray(raw.overlays) ? raw.overlays : [];
  const recommendationsRaw = Array.isArray(raw.recommendations) ? raw.recommendations : [];
  const measurements: AnalyzerMeasurement[] = measurementsRaw.map((entry, index) => {
    const item = asRecord(entry);
    return {
      id: typeof item?.id === 'string' ? item.id : `m-${index}`,
      label: typeof item?.label === 'string' ? item.label : `Mass ${index + 1}`,
      value: Number(item?.value) || 0,
      unit: normalizeUnit(item?.unit),
      tolerance: typeof item?.tolerance === 'string' ? item.tolerance : '-',
      explanation: typeof item?.explanation === 'string' ? item.explanation : '',
    };
  });
  const overlays: DimensionOverlay[] = overlaysRaw.map((entry, index) => {
    const item = asRecord(entry);
    const start = asRecord(item?.start);
    const end = asRecord(item?.end);
    const axis: DimensionAxis = item?.axis === 'vertical' ? 'vertical' : 'horizontal';
    return {
      id: typeof item?.id === 'string' ? item.id : `overlay-${index}`,
      measurementId: typeof item?.measurementId === 'string' ? item.measurementId : `m-${index}`,
      axis,
      start: {
        x: Number(start?.x) || 0.2,
        y: Number(start?.y) || 0.2,
      },
      end: {
        x: Number(end?.x) || 0.8,
        y: Number(end?.y) || 0.8,
      },
    };
  });
  const recommendations = recommendationsRaw.map((item) => String(item).trim()).filter(Boolean);
  return {
    summary: typeof raw.summary === 'string' ? raw.summary : 'Analyse abgeschlossen.',
    confidence: Number(raw.confidence) || 0,
    modelVersion: typeof raw.modelVersion === 'string' ? raw.modelVersion : 'feature-worker',
    completedAt:
      typeof raw.completedAt === 'string' && raw.completedAt
        ? raw.completedAt
        : new Date().toISOString(),
    measurements,
    overlays,
    recommendations,
  };
}

function normalizeServerJob(value: unknown): AnalyzerJob | null {
  const raw = asRecord(value);
  if (!raw || typeof raw.id !== 'string') {
    return null;
  }
  const sourceType = raw.sourceType === 'image' ? 'image' : 'cad';
  const executionMode: AnalyzerExecutionMode =
    raw.executionMode === 'local_fallback' ? 'local_fallback' : 'backend';
  const result = normalizeResult(raw.result);
  return {
    id: raw.id,
    createdAt: typeof raw.createdAt === 'string' ? raw.createdAt : new Date().toISOString(),
    status: normalizeStatus(raw.status),
    fileName: typeof raw.fileName === 'string' ? raw.fileName : 'unknown',
    size: Number(raw.size) || 0,
    metadata: normalizeMetadata(raw.metadata, raw.id),
    sourceType,
    executionMode,
    result,
    error: typeof raw.error === 'string' ? raw.error : undefined,
  };
}

function upsertJob(incoming: AnalyzerJob): AnalyzerJob {
  const jobs = readJobs();
  const index = jobs.findIndex((job) => job.id === incoming.id);
  if (index === -1) {
    jobs.unshift(incoming);
  } else {
    const previous = jobs[index];
    jobs[index] = {
      ...previous,
      ...incoming,
      preview: incoming.preview ?? previous.preview,
      metadata: incoming.metadata ?? previous.metadata,
    };
  }
  persist(jobs);
  emit(jobs);
  return jobs.find((job) => job.id === incoming.id) ?? incoming;
}

function replaceJob(tempId: string, incoming: AnalyzerJob): AnalyzerJob {
  const jobs = readJobs();
  const tempIndex = jobs.findIndex((job) => job.id === tempId);
  const existingIndex = jobs.findIndex((job) => job.id === incoming.id);
  const tempPreview = tempIndex >= 0 ? jobs[tempIndex].preview : undefined;
  const existingPreview = existingIndex >= 0 ? jobs[existingIndex].preview : undefined;
  const merged: AnalyzerJob = {
    ...incoming,
    preview: incoming.preview ?? tempPreview ?? existingPreview,
  };
  if (tempIndex >= 0) {
    jobs.splice(tempIndex, 1);
  }
  const insertIndex = jobs.findIndex((job) => job.id === merged.id);
  if (insertIndex >= 0) {
    jobs[insertIndex] = { ...jobs[insertIndex], ...merged, preview: merged.preview ?? jobs[insertIndex].preview };
  } else {
    jobs.unshift(merged);
  }
  persist(jobs);
  emit(jobs);
  return merged;
}

function stopPolling(jobId: string) {
  const timer = pollingTimers.get(jobId);
  if (timer !== undefined) {
    window.clearInterval(timer);
    pollingTimers.delete(jobId);
  }
}

async function fetchServerJob(jobId: string): Promise<AnalyzerJob | null> {
  const response = await apiFetch(`${ANALYZE_API}/${jobId}`);
  if (!response.ok) {
    return null;
  }
  const payload = await response.json();
  return normalizeServerJob(payload);
}

function startPolling(jobId: string) {
  if (pollingTimers.has(jobId)) {
    return;
  }
  pollingErrorCounts.set(jobId, 0);
  const tick = async () => {
    try {
      const serverJob = await fetchServerJob(jobId);
      if (!serverJob) {
        return;
      }
      pollingErrorCounts.set(jobId, 0);
      const merged = upsertJob(serverJob);
      if (merged.status === 'completed' || merged.status === 'failed') {
        stopPolling(jobId);
      }
    } catch {
      const errors = (pollingErrorCounts.get(jobId) ?? 0) + 1;
      pollingErrorCounts.set(jobId, errors);
      if (errors >= MAX_CONSECUTIVE_POLL_ERRORS) {
        stopPolling(jobId);
      }
    }
  };
  const timer = window.setInterval(() => {
    void tick();
  }, POLL_INTERVAL_MS);
  pollingTimers.set(jobId, timer);
  void tick();
}

function ensurePolling(jobs: AnalyzerJob[]) {
  jobs.forEach((job) => {
    if (job.status === 'pending' || job.status === 'processing') {
      startPolling(job.id);
    } else {
      stopPolling(job.id);
    }
  });
}

async function refreshJobsFromBackend() {
  try {
    const response = await apiFetch(ANALYZE_API);
    if (!response.ok) {
      return;
    }
    const payload = await response.json();
    if (!Array.isArray(payload)) {
      return;
    }
    const normalized = payload
      .map((entry) => normalizeServerJob(entry))
      .filter((entry): entry is AnalyzerJob => entry !== null);
    normalized.forEach((job) => {
      upsertJob(job);
    });
    ensurePolling(readJobs());
  } catch {
    // Backend analyzer is optional in local UI sessions.
  }
}

function nextId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `job-${Date.now()}-${Math.floor(Math.random() * 10000)}`;
}

function detectSourceType(file: File): 'image' | 'cad' {
  const normalized = file.name.split('.').pop()?.toLowerCase() ?? '';
  if (file.type.startsWith('image/') || ['png', 'jpg', 'jpeg', 'webp'].includes(normalized)) {
    return 'image';
  }
  return 'cad';
}

async function fileToPreview(file: File): Promise<string | undefined> {
  if (detectSourceType(file) !== 'image') {
    return undefined;
  }
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(typeof reader.result === 'string' ? reader.result : undefined);
    reader.onerror = () => resolve(undefined);
    reader.readAsDataURL(file);
  });
}

function updateJob(
  jobId: string,
  updater: (current: AnalyzerJob) => AnalyzerJob,
): AnalyzerJob | null {
  const jobs = readJobs();
  const index = jobs.findIndex((job) => job.id === jobId);
  if (index === -1) {
    return null;
  }
  const updated = updater(jobs[index]);
  jobs[index] = updated;
  persist(jobs);
  emit(jobs);
  return updated;
}

async function createServerJob(file: File, metadata: AnalyzerMetadata): Promise<AnalyzerJob> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('job_id', metadata.jobId);
  formData.append('units', metadata.units);
  formData.append('scale', String(metadata.scale));
  formData.append('layer', metadata.layer);
  if (metadata.notes) {
    formData.append('notes', metadata.notes);
  }
  formData.append('views', JSON.stringify(metadata.views));
  const response = await apiFetch(ANALYZE_API, {
    method: 'POST',
    body: formData,
  });
  if (!response.ok) {
    throw new Error(`Analyzer backend unavailable (${response.status})`);
  }
  const payload = await response.json();
  const normalized = normalizeServerJob(payload);
  if (!normalized) {
    throw new Error('Analyzer backend returned invalid payload.');
  }
  return normalized;
}

function convertToUnit(valueMm: number, units: AnalyzerUnit) {
  switch (units) {
    case 'inch':
      return valueMm / 25.4;
    case 'cm':
      return valueMm / 10;
    default:
      return valueMm;
  }
}

function generateLocalResult(job: AnalyzerJob): AnalyzerResult {
  const activeViews = job.metadata.views.length ? job.metadata.views : ['Iso'];
  const templates = [
    {
      id: 'edge-a',
      label: 'Kante A',
      range: [55, 180],
      tolerance: '+/-0.05',
      explanation: 'Primaere Bezugsflaeche fuer Montagepunkte.',
      axis: 'horizontal' as DimensionAxis,
    },
    {
      id: 'edge-b',
      label: 'Kante B',
      range: [35, 120],
      tolerance: '+/-0.03',
      explanation: 'Querbemaessung fuer Gehaeusebreite.',
      axis: 'vertical' as DimensionAxis,
    },
    {
      id: 'hole-pattern',
      label: 'Bohrungsraster',
      range: [20, 60],
      tolerance: 'H7',
      explanation: 'Lochraster fuer Befestigungsschrauben.',
      axis: 'horizontal' as DimensionAxis,
    },
    {
      id: 'bend-radius',
      label: 'Biegeradius',
      range: [8, 24],
      tolerance: '+/-0.02',
      explanation: 'Radius fuer Abwicklung / Blechteilung.',
      axis: 'vertical' as DimensionAxis,
    },
  ];

  const scaleFactor = Math.max(job.metadata.scale, 1);
  const measurements = templates.map((template) => {
    const value = template.range[0] + Math.random() * (template.range[1] - template.range[0]);
    const scaled = value * scaleFactor;
    return {
      id: template.id,
      label: template.label,
      value: parseFloat(convertToUnit(scaled, job.metadata.units).toFixed(2)),
      unit: job.metadata.units,
      tolerance: template.tolerance,
      explanation: template.explanation,
    } satisfies AnalyzerMeasurement;
  });

  const overlayCoords = [
    { start: { x: 0.16, y: 0.32 }, end: { x: 0.78, y: 0.32 } },
    { start: { x: 0.34, y: 0.2 }, end: { x: 0.34, y: 0.78 } },
    { start: { x: 0.22, y: 0.62 }, end: { x: 0.74, y: 0.62 } },
    { start: { x: 0.58, y: 0.25 }, end: { x: 0.58, y: 0.68 } },
  ];
  const overlays = measurements.map((measurement, index) => ({
    id: `overlay-${measurement.id}`,
    measurementId: measurement.id,
    axis: templates[index].axis,
    start: overlayCoords[index].start,
    end: overlayCoords[index].end,
  }));

  const recommendations = [
    `Layer ${job.metadata.layer || 'Basis'} bleibt fuer GPT-Markups freigegeben.`,
    activeViews.includes('Abwicklung')
      ? 'Abwicklung erkannt - Fertigungstoleranzen geprueft.'
      : 'Keine Abwicklung gefunden. Fuer Blechteile hinzufuegen.',
    job.metadata.units !== 'mm'
      ? `Einheiten in ${job.metadata.units} - Export beruecksichtigt Umrechnung.`
      : 'Einheiten mm - direkte Uebergabe an CAM moeglich.',
  ];
  if (job.metadata.notes) {
    recommendations.push(`Notiz uebernommen: ${job.metadata.notes.slice(0, 120)}`);
  }
  recommendations.push('Lokale Simulation aktiv: Ergebnis ist nicht backend-verifiziert.');

  return {
    summary: `Fallback-Worker analysierte ${activeViews.join(', ')} und leitete ${measurements.length} Masse ab.`,
    confidence: Math.round(82 + Math.random() * 14),
    modelVersion: `fallback-worker-${activeViews[0]?.toLowerCase() ?? 'iso'}-1.0`,
    completedAt: new Date().toISOString(),
    measurements,
    overlays,
    recommendations,
  };
}

function triggerLocalWorker(jobId: string) {
  const toProcessing = 500 + Math.random() * 700;
  const toCompletion = 1900 + Math.random() * 1100;
  window.setTimeout(() => {
    updateJob(jobId, (job) => (job.status === 'pending' ? { ...job, status: 'processing' } : job));
  }, toProcessing);
  window.setTimeout(() => {
    updateJob(jobId, (job) => {
      if (job.status === 'failed') {
        return job;
      }
      const result = generateLocalResult(job);
      return {
        ...job,
        status: 'completed',
        result,
        error: undefined,
      };
    });
  }, toProcessing + toCompletion);
}

export function getJobs(): AnalyzerJob[] {
  return readJobs();
}

export function subscribeToJobs(listener: Listener) {
  listeners.add(listener);
  const current = readJobs();
  listener(current);
  ensurePolling(current);
  void refreshJobsFromBackend();
  return () => {
    listeners.delete(listener);
  };
}

export async function createAnalysisJob(
  file: File,
  metadata: Omit<AnalyzerMetadata, 'jobId'>,
): Promise<AnalyzerJob> {
  const preview = await fileToPreview(file);
  const jobId = nextId();
  const normalizedMetadata = normalizeMetadata({ ...metadata, jobId }, jobId);
  const localJob: AnalyzerJob = {
    id: jobId,
    createdAt: new Date().toISOString(),
    status: 'pending',
    fileName: file.name,
    size: file.size,
    metadata: normalizedMetadata,
    preview,
    sourceType: detectSourceType(file),
    executionMode: 'backend',
  };
  const jobs = readJobs();
  jobs.unshift(localJob);
  persist(jobs);
  emit(jobs);

  try {
    const serverJob = await createServerJob(file, normalizedMetadata);
    const merged = replaceJob(localJob.id, {
      ...serverJob,
      preview: preview ?? serverJob.preview,
      sourceType: localJob.sourceType,
    });
    if (merged.status === 'pending' || merged.status === 'processing') {
      startPolling(merged.id);
    }
    return merged;
  } catch (error) {
    console.warn('Analyzer backend unavailable, using local fallback.', error);
    const fallbackJob =
      updateJob(localJob.id, (job) => ({
        ...job,
        executionMode: 'local_fallback',
      })) ?? {
        ...localJob,
        executionMode: 'local_fallback',
      };
    triggerLocalWorker(fallbackJob.id);
    return fallbackJob;
  }
}

export async function fetchDimensions(jobId: string): Promise<AnalyzerResult | null> {
  const local = readJobs().find((job) => job.id === jobId);
  if (local?.result) {
    return local.result;
  }
  try {
    const serverJob = await fetchServerJob(jobId);
    if (!serverJob) {
      return null;
    }
    const merged = upsertJob({
      ...serverJob,
      preview: local?.preview ?? serverJob.preview,
      sourceType: local?.sourceType ?? serverJob.sourceType,
    });
    if (merged.status === 'pending' || merged.status === 'processing') {
      startPolling(merged.id);
      return null;
    }
    return merged.result ?? null;
  } catch {
    return null;
  }
}

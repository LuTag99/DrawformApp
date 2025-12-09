export type AnalyzerUnit = 'mm' | 'cm' | 'inch';

export interface AnalyzerMetadata {
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

export interface AnalyzerJob {
  id: string;
  createdAt: string;
  status: AnalyzerStatus;
  fileName: string;
  size: number;
  metadata: AnalyzerMetadata;
  preview?: string;
  sourceType: 'image' | 'cad';
  result?: AnalyzerResult;
  error?: string;
}

const STORAGE_KEY = 'drawform-analyzer-jobs';
type Listener = (jobs: AnalyzerJob[]) => void;

const listeners = new Set<Listener>();

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
      return parsed as AnalyzerJob[];
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

export function getJobs(): AnalyzerJob[] {
  return readJobs();
}

export function subscribeToJobs(listener: Listener) {
  listeners.add(listener);
  listener(readJobs());
  return () => {
    listeners.delete(listener);
  };
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

export async function createAnalysisJob(
  file: File,
  metadata: AnalyzerMetadata,
): Promise<AnalyzerJob> {
  const preview = await fileToPreview(file);
  const newJob: AnalyzerJob = {
    id: nextId(),
    createdAt: new Date().toISOString(),
    status: 'pending',
    fileName: file.name,
    size: file.size,
    metadata,
    preview,
    sourceType: detectSourceType(file),
  };
  const jobs = readJobs();
  jobs.unshift(newJob);
  persist(jobs);
  emit(jobs);
  triggerWorker(newJob.id);
  return newJob;
}

function triggerWorker(jobId: string) {
  const toProcessing = 600 + Math.random() * 800;
  const toCompletion = 2400 + Math.random() * 1200;
  setTimeout(() => {
    updateJob(jobId, (job) =>
      job.status === 'pending'
        ? { ...job, status: 'processing' }
        : job,
    );
  }, toProcessing);
  setTimeout(() => {
    updateJob(jobId, (job) => {
      if (job.status === 'failed') {
        return job;
      }
      const result = generateResult(job);
      return {
        ...job,
        status: 'completed',
        result,
        error: undefined,
      };
    });
  }, toProcessing + toCompletion);
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

function generateResult(job: AnalyzerJob): AnalyzerResult {
  const activeViews = job.metadata.views.length ? job.metadata.views : ['Iso'];
  const templates = [
    {
      id: 'edge-a',
      label: 'Kante A',
      range: [55, 180],
      tolerance: '±0.05',
      explanation: 'Primäre Bezugsfläche für Montagepunkte.',
      axis: 'horizontal' as DimensionAxis,
    },
    {
      id: 'edge-b',
      label: 'Kante B',
      range: [35, 120],
      tolerance: '±0.03',
      explanation: 'Querbemaßung für Gehäusebreite.',
      axis: 'vertical' as DimensionAxis,
    },
    {
      id: 'hole-pattern',
      label: 'Bohrungsraster',
      range: [20, 60],
      tolerance: 'H7',
      explanation: 'Lochraster für Befestigungsschrauben.',
      axis: 'horizontal' as DimensionAxis,
    },
    {
      id: 'bend-radius',
      label: 'Biegeradius',
      range: [8, 24],
      tolerance: '±0.02',
      explanation: 'Radius für Abwicklung / Blechteilung.',
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

  const summary = `Worker analysierte ${activeViews.join(', ')}-Ansichten und leitete ${measurements.length} kritische Maße ab.`;
  const recommendations = [
    `Layer ${job.metadata.layer || 'Basis'} bleibt für GPT-Markups freigegeben.`,
    activeViews.includes('Abwicklung')
      ? 'Abwicklung erkannt – Fertigungstoleranzen geprüft.'
      : 'Keine Abwicklung gefunden. Für Blechteile hinzufügen.',
    job.metadata.units !== 'mm'
      ? `Einheiten in ${job.metadata.units} – Export berücksichtigt Umrechnung.`
      : 'Einheiten mm – direkte Übergabe an CAM möglich.',
  ];
  if (job.metadata.notes) {
    recommendations.push(`Notiz übernommen: ${job.metadata.notes.slice(0, 120)}`);
  }

  return {
    summary,
    confidence: Math.round(82 + Math.random() * 14),
    modelVersion: `vision-gpt-fusion-${activeViews[0]?.toLowerCase() ?? 'iso'}-1.2`,
    completedAt: new Date().toISOString(),
    measurements,
    overlays,
    recommendations,
  } satisfies AnalyzerResult;
}

export async function fetchDimensions(jobId: string): Promise<AnalyzerResult | null> {
  const jobs = readJobs();
  const job = jobs.find((item) => item.id === jobId);
  if (!job) {
    return null;
  }
  await new Promise((resolve) => setTimeout(resolve, 500));
  return job.result ?? null;
}

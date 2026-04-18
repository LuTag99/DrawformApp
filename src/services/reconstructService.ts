import { authorizedFetch } from './apiClient';
import { uploadReconstructInput } from './firebaseStorageService';

export type ReconstructStatus = 'pending' | 'processing' | 'completed' | 'failed';

export interface ReconstructDimensions {
  width: number;
  height: number;
  depth: number;
}

export interface ReconstructResult {
  stl_available: boolean;
  step_available: boolean;
  pdf_available: boolean;
  vertex_count: number;
  triangle_count: number;
  filled_voxel_ratio: number;
  dimensions_mm: ReconstructDimensions;
  completedAt: string;
}

export interface ReconstructJob {
  id: string;
  createdAt: string;
  status: ReconstructStatus;
  partName: string;
  totalSize: number;
  dimensionsMm: ReconstructDimensions;
  progress?: string;
  result?: ReconstructResult;
  error?: string;
}

const STORAGE_KEY = 'drawform-reconstruct-jobs';
const API_BASE = '/api/reconstruct';
const POLL_INTERVAL_MS = 1500;
const MAX_CONSECUTIVE_POLL_ERRORS = 30;

type Listener = (jobs: ReconstructJob[]) => void;

const listeners = new Set<Listener>();
const pollingTimers = new Map<string, number>();
const pollingErrorCounts = new Map<string, number>();

// --------------------------------------------------------------------------
// LocalStorage persistence
// --------------------------------------------------------------------------

function readJobs(): ReconstructJob[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as ReconstructJob[]) : [];
  } catch {
    return [];
  }
}

function persist(jobs: ReconstructJob[]) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(jobs));
  } catch {
    // Storage full or unavailable
  }
}

function emit(jobs?: ReconstructJob[]) {
  const snapshot = jobs ?? readJobs();
  listeners.forEach((l) => l(snapshot));
}

// --------------------------------------------------------------------------
// Normalization helpers
// --------------------------------------------------------------------------

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : null;
}

function normalizeStatus(value: unknown): ReconstructStatus {
  if (value === 'processing' || value === 'completed' || value === 'failed') return value;
  return 'pending';
}

function normalizeDims(value: unknown): ReconstructDimensions {
  const r = asRecord(value);
  return {
    width: Number(r?.width) || 100,
    height: Number(r?.height) || 100,
    depth: Number(r?.depth) || 100,
  };
}

function normalizeResult(value: unknown): ReconstructResult | undefined {
  const r = asRecord(value);
  if (!r) return undefined;
  return {
    stl_available: Boolean(r.stl_available),
    step_available: Boolean(r.step_available),
    pdf_available: Boolean(r.pdf_available),
    vertex_count: Number(r.vertex_count) || 0,
    triangle_count: Number(r.triangle_count) || 0,
    filled_voxel_ratio: Number(r.filled_voxel_ratio) || 0,
    dimensions_mm: normalizeDims(r.dimensions_mm),
    completedAt: typeof r.completedAt === 'string' ? r.completedAt : new Date().toISOString(),
  };
}

function normalizeServerJob(value: unknown): ReconstructJob | null {
  const r = asRecord(value);
  if (!r || typeof r.id !== 'string') return null;
  return {
    id: r.id,
    createdAt: typeof r.createdAt === 'string' ? r.createdAt : new Date().toISOString(),
    status: normalizeStatus(r.status),
    partName: typeof r.partName === 'string' ? r.partName : 'Bauteil',
    totalSize: Number(r.totalSize) || 0,
    dimensionsMm: normalizeDims(r.dimensionsMm),
    progress: typeof r.progress === 'string' ? r.progress : undefined,
    result: normalizeResult(r.result),
    error: typeof r.error === 'string' ? r.error : undefined,
  };
}

// --------------------------------------------------------------------------
// Job store
// --------------------------------------------------------------------------

function upsertJob(incoming: ReconstructJob): ReconstructJob {
  const jobs = readJobs();
  const idx = jobs.findIndex((j) => j.id === incoming.id);
  if (idx === -1) {
    jobs.unshift(incoming);
  } else {
    jobs[idx] = { ...jobs[idx], ...incoming };
  }
  persist(jobs);
  emit(jobs);
  return jobs.find((j) => j.id === incoming.id) ?? incoming;
}

// --------------------------------------------------------------------------
// Polling
// --------------------------------------------------------------------------

function stopPolling(jobId: string) {
  const timer = pollingTimers.get(jobId);
  if (timer !== undefined) {
    window.clearInterval(timer);
    pollingTimers.delete(jobId);
  }
}

async function fetchServerJob(jobId: string): Promise<ReconstructJob | null> {
  try {
    const response = await authorizedFetch(`${API_BASE}/${jobId}`);
    if (!response.ok) return null;
    return normalizeServerJob(await response.json());
  } catch {
    return null;
  }
}

function startPolling(jobId: string) {
  if (pollingTimers.has(jobId)) return;
  pollingErrorCounts.set(jobId, 0);
  const tick = async () => {
    const serverJob = await fetchServerJob(jobId);
    if (!serverJob) {
      const errors = (pollingErrorCounts.get(jobId) ?? 0) + 1;
      pollingErrorCounts.set(jobId, errors);
      if (errors >= MAX_CONSECUTIVE_POLL_ERRORS) {
        stopPolling(jobId);
      }
      return;
    }
    pollingErrorCounts.set(jobId, 0);
    const merged = upsertJob(serverJob);
    if (merged.status === 'completed' || merged.status === 'failed') {
      stopPolling(jobId);
    }
  };
  const timer = window.setInterval(() => void tick(), POLL_INTERVAL_MS);
  pollingTimers.set(jobId, timer);
  void tick();
}

function ensurePolling(jobs: ReconstructJob[]) {
  jobs.forEach((j) => {
    if (j.status === 'pending' || j.status === 'processing') {
      startPolling(j.id);
    } else {
      stopPolling(j.id);
    }
  });
}

async function refreshFromBackend() {
  try {
    const response = await authorizedFetch(API_BASE);
    if (!response.ok) return;
    const payload = await response.json();
    if (!Array.isArray(payload)) return;
    payload
      .map(normalizeServerJob)
      .filter((j): j is ReconstructJob => j !== null)
      .forEach((j) => upsertJob(j));
    ensurePolling(readJobs());
  } catch {
    // Backend optional
  }
}

// --------------------------------------------------------------------------
// Public API
// --------------------------------------------------------------------------

export function getReconstructJobs(): ReconstructJob[] {
  return readJobs();
}

export function subscribeToReconstructJobs(listener: Listener): () => void {
  listeners.add(listener);
  const current = readJobs();
  listener(current);
  ensurePolling(current);
  void refreshFromBackend();
  return () => listeners.delete(listener);
}

export interface ReconstructParams {
  front: File;
  top: File;
  left: File;
  right: File;
  back: File;
  partName: string;
  widthMm: number;
  heightMm: number;
  depthMm: number;
}

export async function createReconstructJob(params: ReconstructParams): Promise<ReconstructJob> {
  const formData = new FormData();
  formData.append('front', params.front);
  formData.append('top', params.top);
  formData.append('left', params.left);
  formData.append('right', params.right);
  formData.append('back', params.back);
  formData.append('part_name', params.partName);
  formData.append('width_mm', String(params.widthMm));
  formData.append('height_mm', String(params.heightMm));
  formData.append('depth_mm', String(params.depthMm));

  const response = await authorizedFetch(API_BASE, { method: 'POST', body: formData });
  if (!response.ok) {
    const detail = await response.text().catch(() => String(response.status));
    throw new Error(`Rekonstruktion fehlgeschlagen: ${detail}`);
  }
  const payload = await response.json();
  const job = normalizeServerJob(payload);
  if (!job) throw new Error('Server returned invalid job payload.');

  // Storage-Mirror laeuft erst nachdem der Server die kanonische jobId
  // vergeben hat, damit der Pfad users/{uid}/reconstruct/{jobId}/input/... der
  // tatsaechlichen Job-ID entspricht (siehe DATA_MODEL.md).
  void Promise.all([
    uploadReconstructInput(params.front, job.id, 'front'),
    uploadReconstructInput(params.top, job.id, 'top'),
    uploadReconstructInput(params.left, job.id, 'left'),
    uploadReconstructInput(params.right, job.id, 'right'),
    uploadReconstructInput(params.back, job.id, 'back'),
  ]).catch((error) => {
    console.warn('Reconstruct-Quellbilder konnten nicht in Firebase Storage gespeichert werden.', error);
  });

  upsertJob(job);
  startPolling(job.id);
  return job;
}

export async function downloadReconstructFile(jobId: string, type: 'stl' | 'step' | 'pdf') {
  const response = await authorizedFetch(`${API_BASE}/${jobId}/download?type=${type}`);
  if (!response.ok) {
    const detail = await response.text().catch(() => String(response.status));
    throw new Error(detail || `Download fehlgeschlagen (${response.status}).`);
  }
  const blob = await response.blob();
  const blobUrl = URL.createObjectURL(blob);
  const fallbackName = `reconstruct-${jobId}.${type}`;
  const disposition = response.headers.get('content-disposition') ?? '';
  const fileName = disposition.match(/filename="([^"]+)"/i)?.[1] ?? fallbackName;
  const anchor = document.createElement('a');
  anchor.href = blobUrl;
  anchor.download = fileName;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(blobUrl), 0);
}

export function clearReconstructJobs() {
  persist([]);
  emit([]);
}

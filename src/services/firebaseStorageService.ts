import { getDownloadURL, ref, uploadBytes } from 'firebase/storage';
import { firebaseConfigured, getFirebaseAuth, getFirebaseStorage } from '../lib/firebase';

// Kanonische Storage-Pfade gemaess server/docs/firebase/DATA_MODEL.md:
//   users/{uid}/avatar/<name>
//   users/{uid}/exports/{exportId}/source/<name>
//   users/{uid}/exports/{exportId}/output/<name>
//   users/{uid}/reconstruct/{jobId}/input/<role>-<name>
//   users/{uid}/analyzer/{jobId}/input/<name>
// IDs werden fachlich vergeben, nicht ueber Zufallsordner.

export type StorageTarget =
  | { kind: 'avatar' }
  | { kind: 'export-source'; exportId: string }
  | { kind: 'export-output'; exportId: string }
  | { kind: 'reconstruct-input'; jobId: string }
  | { kind: 'analyzer-input'; jobId: string };

interface UploadOptions {
  target: StorageTarget;
  fileName: string;
  contentType?: string;
}

export interface StoredAsset {
  downloadUrl: string;
  fullPath: string;
}

function sanitizeSegment(value: string) {
  return value.replace(/[^A-Za-z0-9._-]+/g, '_').replace(/^_+|_+$/g, '') || 'file';
}

function assertNonEmptyId(value: string, label: string) {
  if (!value || !value.trim()) {
    throw new Error(`${label} darf nicht leer sein.`);
  }
}

function resolveTargetPath(uid: string, target: StorageTarget, safeFile: string): string {
  switch (target.kind) {
    case 'avatar':
      return `users/${uid}/avatar/${safeFile}`;
    case 'export-source':
      assertNonEmptyId(target.exportId, 'exportId');
      return `users/${uid}/exports/${sanitizeSegment(target.exportId)}/source/${safeFile}`;
    case 'export-output':
      assertNonEmptyId(target.exportId, 'exportId');
      return `users/${uid}/exports/${sanitizeSegment(target.exportId)}/output/${safeFile}`;
    case 'reconstruct-input':
      assertNonEmptyId(target.jobId, 'jobId');
      return `users/${uid}/reconstruct/${sanitizeSegment(target.jobId)}/input/${safeFile}`;
    case 'analyzer-input':
      assertNonEmptyId(target.jobId, 'jobId');
      return `users/${uid}/analyzer/${sanitizeSegment(target.jobId)}/input/${safeFile}`;
  }
}

function buildFileName(raw: string, { unique = false }: { unique?: boolean } = {}) {
  const safe = sanitizeSegment(raw);
  if (!unique) {
    return safe;
  }
  const suffix =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID().slice(0, 8)
      : Math.random().toString(36).slice(2, 10);
  const dot = safe.lastIndexOf('.');
  if (dot <= 0) {
    return `${safe}-${suffix}`;
  }
  return `${safe.slice(0, dot)}-${suffix}${safe.slice(dot)}`;
}

async function uploadAsset(
  blob: Blob | Uint8Array | ArrayBuffer,
  options: UploadOptions,
): Promise<StoredAsset> {
  if (!firebaseConfigured) {
    throw new Error('Firebase Storage ist nicht konfiguriert.');
  }
  const currentUser = getFirebaseAuth().currentUser;
  if (!currentUser) {
    throw new Error('Du bist nicht angemeldet.');
  }
  const safeFile = sanitizeSegment(options.fileName);
  const fullPath = resolveTargetPath(currentUser.uid, options.target, safeFile);
  const storage = getFirebaseStorage();
  const storageRef = ref(storage, fullPath);
  const snapshot = await uploadBytes(storageRef, blob, {
    contentType: options.contentType,
  });
  return {
    downloadUrl: await getDownloadURL(snapshot.ref),
    fullPath: snapshot.ref.fullPath,
  };
}

export async function uploadAvatar(file: File): Promise<StoredAsset> {
  return uploadAsset(file, {
    target: { kind: 'avatar' },
    fileName: buildFileName(file.name, { unique: true }),
    contentType: file.type || undefined,
  });
}

export async function uploadExportSource(
  file: File,
  exportId: string,
): Promise<StoredAsset> {
  return uploadAsset(file, {
    target: { kind: 'export-source', exportId },
    fileName: file.name,
    contentType: file.type || undefined,
  });
}

export async function uploadExportOutput(
  blob: Blob,
  exportId: string,
  fileName: string,
): Promise<StoredAsset> {
  return uploadAsset(blob, {
    target: { kind: 'export-output', exportId },
    fileName,
    contentType: blob.type || undefined,
  });
}

export async function uploadReconstructInput(
  file: File,
  jobId: string,
  role: string,
): Promise<StoredAsset> {
  const safeRole = sanitizeSegment(role);
  return uploadAsset(file, {
    target: { kind: 'reconstruct-input', jobId },
    fileName: `${safeRole}-${sanitizeSegment(file.name)}`,
    contentType: file.type || undefined,
  });
}

export async function uploadAnalyzerInput(
  file: File,
  jobId: string,
): Promise<StoredAsset> {
  return uploadAsset(file, {
    target: { kind: 'analyzer-input', jobId },
    fileName: file.name,
    contentType: file.type || undefined,
  });
}

export function newClientExportId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `exp-${crypto.randomUUID()}`;
  }
  return `exp-${Date.now()}-${Math.floor(Math.random() * 1_000_000)}`;
}

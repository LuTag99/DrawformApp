import { authorizedFetch } from './apiClient';
import {
  newClientExportId,
  uploadExportOutput,
  uploadExportSource,
} from './firebaseStorageService';

export interface ExportResult {
  success: boolean;
  message: string;
  fileName?: string;
  blobUrl?: string;
  storagePath?: string;
  exportId?: string;
}

export interface PdfExportOptions {
  title?: string;
  drawingNo?: string;
  revision?: string;
  author?: string;
  company?: string;
  scale?: string;
  standard?: string;
  projection?: string;
  generalTolerance?: string;
  unit?: string;
  sheet?: string;
  kFactor?: string;
  detailLevel?: number;
  includeFlatPattern?: boolean;
}

export interface DxfExportOptions {
  kFactor?: string;
}

function appendOptionalField(formData: FormData, key: string, value: string | number | undefined) {
  if (value === undefined) {
    return;
  }
  const normalized = String(value).trim();
  if (!normalized) {
    return;
  }
  formData.append(key, normalized);
}

function getFileNameFromDisposition(value: string | null, fallback: string) {
  if (!value) {
    return fallback;
  }
  const match = value.match(/filename="([^"]+)"/i);
  return match?.[1] ?? fallback;
}

async function readErrorMessage(response: Response) {
  const contentType = response.headers.get('content-type') ?? '';
  if (contentType.includes('application/json')) {
    try {
      const payload = (await response.json()) as { detail?: string; message?: string };
      if (payload?.detail) {
        return payload.detail;
      }
      if (payload?.message) {
        return payload.message;
      }
    } catch {
      return `Export failed (${response.status})`;
    }
  }
  const text = await response.text();
  return text || `Export failed (${response.status})`;
}

async function persistExportArtifacts(
  file: File,
  resultBlob: Blob,
  exportId: string,
  resultName: string,
): Promise<string | undefined> {
  try {
    await uploadExportSource(file, exportId);
    const storedResult = await uploadExportOutput(resultBlob, exportId, resultName);
    return storedResult.fullPath;
  } catch (error) {
    console.warn('Firebase Storage Upload fehlgeschlagen.', error);
    return undefined;
  }
}

export async function requestPdfExport(
  file: File,
  options: PdfExportOptions = {},
): Promise<ExportResult> {
  const exportId = newClientExportId();
  const formData = new FormData();
  formData.append('file', file);
  formData.append('format', 'pdf');
  formData.append('export_id', exportId);
  appendOptionalField(formData, 'title', options.title);
  appendOptionalField(formData, 'drawing_no', options.drawingNo);
  appendOptionalField(formData, 'revision', options.revision);
  appendOptionalField(formData, 'author', options.author);
  appendOptionalField(formData, 'company', options.company);
  appendOptionalField(formData, 'scale', options.scale);
  appendOptionalField(formData, 'standard', options.standard);
  appendOptionalField(formData, 'projection', options.projection);
  appendOptionalField(formData, 'general_tolerance', options.generalTolerance);
  appendOptionalField(formData, 'unit', options.unit);
  appendOptionalField(formData, 'sheet', options.sheet);
  appendOptionalField(formData, 'k_factor', options.kFactor);
  appendOptionalField(formData, 'detail_level', options.detailLevel);
  if (options.includeFlatPattern !== undefined) {
    formData.append('include_flat_pattern', options.includeFlatPattern ? '1' : '0');
  }
  try {
    const response = await authorizedFetch('/api/export', {
      method: 'POST',
      body: formData,
    });
    if (!response.ok) {
      return {
        success: false,
        message: await readErrorMessage(response),
      };
    }

    const contentType = response.headers.get('content-type') ?? '';
    if (!contentType.includes('application/pdf')) {
      return {
        success: false,
        message: await readErrorMessage(response),
      };
    }

    const blob = await response.blob();
    const fallbackName = `${file.name.replace(/\.[^.]+$/, '')}.pdf`;
    const fileName = getFileNameFromDisposition(
      response.headers.get('content-disposition'),
      fallbackName,
    );
    const blobUrl = URL.createObjectURL(blob);
    const storagePath = await persistExportArtifacts(file, blob, exportId, fileName);
    return {
      success: true,
      message: storagePath
        ? 'PDF erstellt und in Firebase Storage gespeichert.'
        : 'PDF erstellt.',
      fileName,
      blobUrl,
      storagePath,
      exportId,
    };
  } catch (error) {
    return {
      success: false,
      message: (error as Error)?.message ?? 'Export konnte nicht gestartet werden.',
    };
  }
}

export async function requestDxfExport(
  file: File,
  options: DxfExportOptions = {},
): Promise<ExportResult> {
  const exportId = newClientExportId();
  const formData = new FormData();
  formData.append('file', file);
  formData.append('export_id', exportId);
  appendOptionalField(formData, 'k_factor', options.kFactor);
  try {
    const response = await authorizedFetch('/api/export-dxf', {
      method: 'POST',
      body: formData,
    });
    if (!response.ok) {
      return {
        success: false,
        message: await readErrorMessage(response),
      };
    }

    const contentType = response.headers.get('content-type') ?? '';
    if (!contentType.includes('application/dxf') && !contentType.includes('application/octet-stream')) {
      return {
        success: false,
        message: await readErrorMessage(response),
      };
    }

    const blob = await response.blob();
    const fallbackName = `${file.name.replace(/\.[^.]+$/, '')}_flat.dxf`;
    const fileName = getFileNameFromDisposition(
      response.headers.get('content-disposition'),
      fallbackName,
    );
    const blobUrl = URL.createObjectURL(blob);
    const storagePath = await persistExportArtifacts(file, blob, exportId, fileName);
    return {
      success: true,
      message: storagePath
        ? 'DXF erstellt und in Firebase Storage gespeichert.'
        : 'DXF erstellt.',
      fileName,
      blobUrl,
      storagePath,
      exportId,
    };
  } catch (error) {
    return {
      success: false,
      message: (error as Error)?.message ?? 'DXF-Export konnte nicht gestartet werden.',
    };
  }
}

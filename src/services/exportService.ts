export interface ExportResult {
  success: boolean;
  message: string;
  fileName?: string;
  blobUrl?: string;
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

export async function requestPdfExport(file: File): Promise<ExportResult> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('format', 'pdf');
  try {
    const response = await fetch('/api/export', {
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
    const fileName = getFileNameFromDisposition(response.headers.get('content-disposition'), fallbackName);
    const blobUrl = URL.createObjectURL(blob);
    return {
      success: true,
      message: 'PDF erstellt.',
      fileName,
      blobUrl,
    };
  } catch (error) {
    return {
      success: false,
      message: (error as Error)?.message ?? 'Export konnte nicht gestartet werden.',
    };
  }
}

export async function requestDxfExport(file: File): Promise<ExportResult> {
  const formData = new FormData();
  formData.append('file', file);
  try {
    const response = await fetch('/api/export-dxf', {
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
    const fileName = getFileNameFromDisposition(response.headers.get('content-disposition'), fallbackName);
    const blobUrl = URL.createObjectURL(blob);
    return {
      success: true,
      message: 'DXF erstellt.',
      fileName,
      blobUrl,
    };
  } catch (error) {
    return {
      success: false,
      message: (error as Error)?.message ?? 'DXF-Export konnte nicht gestartet werden.',
    };
  }
}

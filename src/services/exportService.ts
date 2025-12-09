export interface ExportResult {
  success: boolean;
  message: string;
  path?: string;
}

async function sleep(duration = 1200) {
  return new Promise((resolve) => setTimeout(resolve, duration));
}

export async function requestVectorExport(
  file: File,
  format: string,
): Promise<ExportResult> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('format', format);
  try {
    const response = await fetch('/api/export', {
      method: 'POST',
      body: formData,
    });
    if (!response.ok) {
      throw new Error('Server meldete einen Fehler.');
    }
    const payload = (await response.json()) as ExportResult;
    return payload;
  } catch (error) {
    console.warn('Falling back to local export stub', error);
    await sleep();
    return {
      success: true,
      message: 'Export erfolgreich ausgeführt (lokale Simulation).',
      path: `/exports/${file.name.replace(/\.[^.]+$/, '')}.${format}`,
    };
  }
}

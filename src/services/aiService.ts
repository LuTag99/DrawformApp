export interface AiInsight {
  narrative: string;
  chips: string[];
}

const fallbackInsight: AiInsight = {
  narrative:
    'Die Pipeline läuft stabil. Aktiviere automatische Prüfungen, um wiederkehrende CAD-Tasks vom KI-Co-Piloten erledigen zu lassen.',
  chips: ['AI Ready', '0% Fehler', 'Glass Workflow'],
};

/**
 * Fetch an AI-generated dashboard insight.
 *
 * Uses the backend proxy at /api/ai-insight so that API keys are never
 * shipped to the browser.  Falls back to a static insight when the
 * backend is unavailable or the endpoint is not yet implemented.
 */
export async function fetchAiInsight(
  statusSummary: string,
): Promise<AiInsight> {
  try {
    const response = await fetch('/api/ai-insight', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ statusSummary }),
    });
    if (!response.ok) {
      return fallbackInsight;
    }
    const data = await response.json();
    return {
      narrative: typeof data.narrative === 'string' && data.narrative ? data.narrative : fallbackInsight.narrative,
      chips: Array.isArray(data.chips) && data.chips.length ? data.chips : fallbackInsight.chips,
    };
  } catch {
    // Backend AI endpoint is optional — fall back silently.
    return fallbackInsight;
  }
}

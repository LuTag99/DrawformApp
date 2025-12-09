export interface AiInsight {
  narrative: string;
  chips: string[];
}

const AI_ENDPOINT = 'https://api.openai.com/v1/chat/completions';
const AI_MODEL = 'gpt-4.1-mini';

const fallbackInsight: AiInsight = {
  narrative:
    'Die Pipeline läuft stabil. Aktiviere automatische Prüfungen, um wiederkehrende CAD-Tasks vom KI-Co-Piloten erledigen zu lassen.',
  chips: ['AI Ready', '0% Fehler', 'Glass Workflow'],
};

export async function fetchAiInsight(
  statusSummary: string,
): Promise<AiInsight> {
  const apiKey = import.meta.env.VITE_OPENAI_API_KEY;
  if (!apiKey) {
    return fallbackInsight;
  }
  try {
    const response = await fetch(AI_ENDPOINT, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model: AI_MODEL,
        temperature: 0.4,
        messages: [
          {
            role: 'system',
            content:
              'Du bist ein AI-Coach für ein CAD/Export Dashboard. Antworte kurz in deutscher Sprache.',
          },
          {
            role: 'user',
            content: `${statusSummary}\nGib die Antwort im Format: INSIGHT: <Text>\nCHIPS: <Chip1>|<Chip2>|<Chip3>`,
          },
        ],
      }),
    });
    if (!response.ok) {
      console.warn('OpenAI response failed', response.statusText);
      return fallbackInsight;
    }
    const data = await response.json();
    const content: string =
      data.choices?.[0]?.message?.content ?? fallbackInsight.narrative;
    const [insightLine, chipsLine] = content.split('CHIPS:');
    const narrative = insightLine?.replace('INSIGHT:', '').trim();
    const chips =
      chipsLine
        ?.split('|')
        .map((chip: string) => chip.trim())
        .filter(Boolean) ?? fallbackInsight.chips;
    return {
      narrative: narrative || fallbackInsight.narrative,
      chips: chips.length ? chips : fallbackInsight.chips,
    };
  } catch (error) {
    console.error('AI insight error', error);
    return fallbackInsight;
  }
}

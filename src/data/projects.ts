export interface Project {
  title: string;
  description: string;
  status: 'In Analyse' | 'Freigegeben' | 'In Freigabe';
  aiScore: number;
}

export const demoProjects: Project[] = [
  {
    title: 'Ioncore Gehäuse',
    description: '3D-Modellierung & Wandstärkenanalyse für IoT-Modul.',
    status: 'In Analyse',
    aiScore: 92,
  },
  {
    title: 'Adaptive Halterung',
    description: 'CAD-Konstruktion mit adaptiver Topologie-Optimierung.',
    status: 'Freigegeben',
    aiScore: 96,
  },
  {
    title: 'Blechbauteil Serie C',
    description: 'Automatisierte Bemaßung inkl. Fertigungsvorschriften.',
    status: 'In Freigabe',
    aiScore: 88,
  },
];

import { HiOutlineFolder } from 'react-icons/hi';
import { demoProjects } from '../../data/projects';
import SectionHeader from '../../components/SectionHeader';

export function ProjectsPage() {
  return (
    <div className="glass-panel shell-card">
      <SectionHeader
        title="Projektübersicht"
        subtitle="AI bewertet Status & Qualität deiner Konstruktionen."
      />
      <div className="stack" style={{ marginTop: '1.2rem' }}>
        {demoProjects.map((project) => (
          <ProjectCard key={project.title} project={project} />
        ))}
      </div>
    </div>
  );
}

function ProjectCard({
  project,
}: {
  project: (typeof demoProjects)[number];
}) {
  return (
    <button
      type="button"
      className="glass-panel--soft"
      style={{
        padding: '1.6rem',
        width: '100%',
        border: 'none',
        textAlign: 'left',
        cursor: 'pointer',
      }}
    >
      <div style={{ display: 'flex', gap: '1.2rem' }}>
        <div
          style={{
            width: 60,
            height: 60,
            borderRadius: 22,
            backgroundImage: 'var(--gradient-accent)',
            display: 'grid',
            placeItems: 'center',
            color: '#fff',
          }}
        >
          <HiOutlineFolder size={28} />
        </div>
        <div style={{ flex: 1 }}>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}
          >
            <h3 style={{ margin: 0 }}>{project.title}</h3>
            <span
              className="chip"
              style={{
                textTransform: 'uppercase',
                letterSpacing: '0.04em',
              }}
            >
              {project.status}
            </span>
          </div>
          <p style={{ color: 'var(--text-secondary)', marginTop: '0.4rem' }}>
            {project.description}
          </p>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              marginTop: '0.8rem',
              fontSize: '0.9rem',
              color: 'var(--text-secondary)',
            }}
          >
            <span>AI Score {project.aiScore}%</span>
            <span>Co-Pilot aktiv</span>
          </div>
        </div>
      </div>
    </button>
  );
}

export default ProjectsPage;

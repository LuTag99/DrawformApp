import { Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from './layouts/AppShell';
import { DashboardPage } from './pages/dashboard/DashboardPage';
import { ProjectsPage } from './pages/projects/ProjectsPage';
import { ExportPage } from './pages/export/ExportPage';
import { AnalyzerPage } from './pages/analyzer/AnalyzerPage';
import { ReconstructPage } from './pages/reconstruct/ReconstructPage';
import { AiBackground } from './components/AiBackground';

export function App() {
  return (
    <div className="app-wrapper">
      <AiBackground />
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route index element={<DashboardPage />} />
          <Route path="analyzer" element={<AnalyzerPage />} />
          <Route path="reconstruct" element={<ReconstructPage />} />
          <Route path="projects" element={<ProjectsPage />} />
          <Route path="export" element={<ExportPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
}

export default App;

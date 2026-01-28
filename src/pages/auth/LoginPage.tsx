import { useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { AuthLayout } from '../../layouts/AuthLayout';
import { GradientButton } from '../../components/GradientButton';
import { useAuth } from '../../hooks/useAuth';

const DEMO_EMAIL = 'demo@drawform.local';
const DEMO_PASSWORD = 'drawform';

export function LoginPage() {
  const { login, register, user, loading } = useAuth();
  const navigate = useNavigate();
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!loading && user) {
    return <Navigate to="/" replace />;
  }

  const handleQuickLogin = async () => {
    setBusy(true);
    let error = await login(DEMO_EMAIL, DEMO_PASSWORD);
    if (error) {
      error = await register(DEMO_EMAIL, DEMO_PASSWORD);
    }
    if (error) {
      setStatus(error);
    } else {
      navigate('/');
    }
    setBusy(false);
  };

  return (
    <AuthLayout
      title="Willkommen"
      subtitle="Starte den Drawform AI Workspace."
    >
      {status && <div className="status-banner status-banner--error">{status}</div>}
      <div className="stack">
        <GradientButton
          type="button"
          label="Anmelden"
          busy={busy}
          busyLabel="Workspace wird geladen..."
          onClick={handleQuickLogin}
        />
      </div>
    </AuthLayout>
  );
}

export default LoginPage;

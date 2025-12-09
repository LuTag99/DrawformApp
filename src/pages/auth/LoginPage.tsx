import { type FormEvent, useState } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { AuthLayout } from '../../layouts/AuthLayout';
import { InputField } from '../../components/InputField';
import { GradientButton } from '../../components/GradientButton';
import { useAuth } from '../../hooks/useAuth';

export function LoginPage() {
  const { login, user, loading } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!loading && user) {
    return <Navigate to="/" replace />;
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    const error = await login(email, password);
    if (error) {
      setStatus(error);
    } else {
      navigate('/');
    }
    setBusy(false);
  };

  return (
    <AuthLayout
      title="Willkommen zurück"
      subtitle="Melde dich in deinem Drawform AI Workspace an."
      footer={
        <>
          Kein Account? <Link to="/register">Registrieren</Link> ·{' '}
          <Link to="/forgot-password">Passwort vergessen</Link>
        </>
      }
    >
      {status && <div className="status-banner status-banner--error">{status}</div>}
      <form onSubmit={handleSubmit} className="stack">
        <InputField
          label="E-Mail"
          type="email"
          required
          placeholder="you@drawform.ai"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <InputField
          label="Passwort"
          type="password"
          required
          placeholder="••••••••"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        <GradientButton
          type="submit"
          label="Anmelden"
          busy={busy}
          busyLabel="AI prüft Anmeldedaten …"
        />
      </form>
    </AuthLayout>
  );
}

export default LoginPage;

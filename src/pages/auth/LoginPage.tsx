import { type FormEvent, useState } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { AuthLayout } from '../../layouts/AuthLayout';
import { InputField } from '../../components/InputField';
import { GradientButton } from '../../components/GradientButton';
import { useAuth } from '../../hooks/useAuth';

export function LoginPage() {
  const { login, loginWithGoogle, user, loading, firebaseConfigured } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [googleBusy, setGoogleBusy] = useState(false);

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

  const handleGoogleLogin = async () => {
    setGoogleBusy(true);
    const error = await loginWithGoogle();
    if (error) {
      setStatus(error);
    } else {
      navigate('/');
    }
    setGoogleBusy(false);
  };

  return (
    <AuthLayout
      title="Willkommen"
      subtitle="Melde dich mit Firebase Auth an und arbeite mit benutzergebundenem Storage."
      footer={
        <>
          Noch kein Konto? <Link to="/register">Registrieren</Link>
        </>
      }
    >
      {!firebaseConfigured && (
        <div className="status-banner status-banner--error">
          Firebase ist noch nicht konfiguriert. Trage zuerst die `VITE_FIREBASE_*` Werte ein.
        </div>
      )}
      {status && <div className="status-banner status-banner--error">{status}</div>}
      <form onSubmit={handleSubmit} className="stack">
        <InputField
          label="E-Mail"
          type="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="you@drawform.ai"
        />
        <InputField
          label="Passwort"
          type="password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          placeholder="Mindestens 6 Zeichen"
        />
        <GradientButton
          type="submit"
          label="Anmelden"
          busy={busy}
          busyLabel="Workspace wird geladen..."
        />
      </form>
      <div className="stack" style={{ marginTop: '1rem' }}>
        <GradientButton
          type="button"
          label="Mit Google anmelden"
          busy={googleBusy}
          busyLabel="Google-Login startet..."
          onClick={handleGoogleLogin}
        />
        <Link to="/forgot-password" style={{ color: 'var(--text-secondary)' }}>
          Passwort vergessen?
        </Link>
      </div>
    </AuthLayout>
  );
}

export default LoginPage;

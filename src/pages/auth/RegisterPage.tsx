import { type FormEvent, useState } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { AuthLayout } from '../../layouts/AuthLayout';
import { InputField } from '../../components/InputField';
import { GradientButton } from '../../components/GradientButton';
import { useAuth } from '../../hooks/useAuth';

export function RegisterPage() {
  const { register, loginWithGoogle, user, loading, firebaseConfigured } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [googleBusy, setGoogleBusy] = useState(false);

  if (!loading && user) {
    return <Navigate to="/" replace />;
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (password !== confirmPassword) {
      setStatus('Die Passwoerter stimmen nicht ueberein.');
      return;
    }
    setBusy(true);
    const error = await register(email, password);
    if (error) {
      setStatus(error);
    } else {
      navigate('/');
    }
    setBusy(false);
  };

  const handleGoogleSignup = async () => {
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
      title="Account erstellen"
      subtitle="Firebase Auth erstellt dein Benutzerkonto fuer eigene Daten und Dateien."
      footer={
        <>
          Bereits dabei? <Link to="/login">Zum Login</Link>
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
        <InputField
          label="Passwort bestaetigen"
          type="password"
          required
          value={confirmPassword}
          onChange={(event) => setConfirmPassword(event.target.value)}
          placeholder="Erneut eingeben"
        />
        <GradientButton
          type="submit"
          label="Workspace anlegen"
          busy={busy}
          busyLabel="Erstelle Workspace..."
        />
      </form>
      <div className="stack" style={{ marginTop: '1rem' }}>
        <GradientButton
          type="button"
          label="Mit Google fortfahren"
          busy={googleBusy}
          busyLabel="Google-Login startet..."
          onClick={handleGoogleSignup}
        />
      </div>
    </AuthLayout>
  );
}

export default RegisterPage;

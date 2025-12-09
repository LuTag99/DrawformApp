import { type FormEvent, useState } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { AuthLayout } from '../../layouts/AuthLayout';
import { InputField } from '../../components/InputField';
import { GradientButton } from '../../components/GradientButton';
import { useAuth } from '../../hooks/useAuth';

export function RegisterPage() {
  const { register, user, loading } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!loading && user) {
    return <Navigate to="/" replace />;
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (password !== confirmPassword) {
      setStatus('Die Passwörter stimmen nicht überein.');
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

  return (
    <AuthLayout
      title="Account erstellen"
      subtitle="Glas-UI, AI Co-Pilot & Export-Automation in einem Workspace."
      footer={
        <>
          Bereits dabei? <Link to="/login">Zum Login</Link>
        </>
      }
    >
      {status && (
        <div
          className={`status-banner ${
            status.startsWith('Profil') ? 'status-banner--success' : 'status-banner--error'
          }`}
        >
          {status}
        </div>
      )}
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
          label="Passwort bestätigen"
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
          busyLabel="Erstelle Glas-Workspace …"
        />
      </form>
    </AuthLayout>
  );
}

export default RegisterPage;

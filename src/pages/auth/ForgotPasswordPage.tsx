import { type FormEvent, useState } from 'react';
import { Link } from 'react-router-dom';
import { AuthLayout } from '../../layouts/AuthLayout';
import { InputField } from '../../components/InputField';
import { GradientButton } from '../../components/GradientButton';
import { useAuth } from '../../hooks/useAuth';

export function ForgotPasswordPage() {
  const { resetPassword, firebaseConfigured } = useAuth();
  const [email, setEmail] = useState('');
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    const message = await resetPassword(email);
    setStatus(message);
    setBusy(false);
  };

  return (
    <AuthLayout
      title="Passwort vergessen?"
      subtitle="Wir senden dir einen Reset-Link – AI sichert deinen Zugang."
      footer={
        <>
          Du erinnerst dich wieder? <Link to="/login">Zurück zum Login</Link>
        </>
      }
    >
      {!firebaseConfigured && (
        <div className="status-banner status-banner--error">
          Firebase ist noch nicht konfiguriert. Trage zuerst die `VITE_FIREBASE_*` Werte ein.
        </div>
      )}
      {status && (
        <div
          className={`status-banner ${
            status.includes('gesendet')
              ? 'status-banner--success'
              : 'status-banner--error'
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
        <GradientButton
          type="submit"
          label="Reset-Link senden"
          busy={busy}
          busyLabel="Sende sicheren Link …"
        />
      </form>
    </AuthLayout>
  );
}

export default ForgotPasswordPage;

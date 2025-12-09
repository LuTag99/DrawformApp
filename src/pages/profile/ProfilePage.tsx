import { type FormEvent, useEffect, useMemo, useState } from 'react';
import SectionHeader from '../../components/SectionHeader';
import { InputField } from '../../components/InputField';
import { GradientButton } from '../../components/GradientButton';
import { useAuth } from '../../hooks/useAuth';

export function ProfilePage() {
  const { user, updateProfile } = useAuth();
  const [avatarUrl, setAvatarUrl] = useState(user?.avatarUrl ?? '');
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      setAvatarUrl(user?.avatarUrl ?? '');
    });
    return () => cancelAnimationFrame(frame);
  }, [user?.avatarUrl]);

  const initials = useMemo(
    () => user?.email?.substring(0, 2).toUpperCase() ?? 'AI',
    [user?.email],
  );

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    const message = await updateProfile({
      avatarUrl,
      currentPassword: currentPassword || undefined,
      newPassword: newPassword || undefined,
    });
    if (message) {
      setStatus(message);
    } else {
      setStatus('Profil aktualisiert.');
      setCurrentPassword('');
      setNewPassword('');
    }
    setBusy(false);
  };

  return (
    <div className="glass-panel shell-card">
      <SectionHeader
        title="Profil & Sicherheit"
        subtitle="Passe dein Glas-Avatar und deine Zugangsdaten an."
      />
      <form onSubmit={handleSubmit} className="stack" style={{ marginTop: '1.4rem' }}>
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: '1.5rem',
            alignItems: 'center',
          }}
        >
          <div
            style={{
              width: 110,
              height: 110,
              borderRadius: 999,
              padding: 6,
              backgroundImage: 'var(--gradient-accent)',
            }}
          >
            <div
              style={{
                width: '100%',
                height: '100%',
                borderRadius: '50%',
                overflow: 'hidden',
                background: 'rgba(15,23,42,0.6)',
                display: 'grid',
                placeItems: 'center',
                fontSize: '1.8rem',
                fontWeight: 600,
              }}
            >
              {avatarUrl ? (
                <img
                  src={avatarUrl}
                  alt="Avatar"
                  style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                  onError={() => setAvatarUrl('')}
                />
              ) : (
                initials
              )}
            </div>
          </div>
          <div className="ai-chip-group">
            {(user?.highlights ?? []).map((chip) => (
              <span key={chip} className="chip">
                {chip}
              </span>
            ))}
          </div>
        </div>
        <InputField
          label="Avatar URL"
          placeholder="https://images.drawform.ai/avatar.png"
          value={avatarUrl}
          onChange={(event) => setAvatarUrl(event.target.value)}
        />
        <div className="stack">
          <InputField
            label="Aktuelles Passwort"
            type="password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
          />
          <InputField
            label="Neues Passwort"
            type="password"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
          />
        </div>
        <GradientButton
          type="submit"
          label="Profil speichern"
          busy={busy}
          busyLabel="Speichere Glas-Profil …"
        />
        {status && (
          <div
            className={`status-banner ${
              status === 'Profil aktualisiert.' ? 'status-banner--success' : 'status-banner--error'
            }`}
          >
            {status}
          </div>
        )}
      </form>
    </div>
  );
}

export default ProfilePage;

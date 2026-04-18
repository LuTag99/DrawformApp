import { type ChangeEvent, type FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import SectionHeader from '../../components/SectionHeader';
import { InputField } from '../../components/InputField';
import { GradientButton } from '../../components/GradientButton';
import { useAuth } from '../../hooks/useAuth';
import { uploadAvatar } from '../../services/firebaseStorageService';

export function ProfilePage() {
  const { user, updateProfile, firebaseConfigured } = useAuth();
  const avatarInputRef = useRef<HTMLInputElement | null>(null);
  const [avatarUrl, setAvatarUrl] = useState(user?.avatarUrl ?? '');
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [avatarBusy, setAvatarBusy] = useState(false);

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
  const canChangePassword = user?.providers.includes('password') ?? false;

  const handleAvatarUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    setAvatarBusy(true);
    setStatus(null);
    try {
      const stored = await uploadAvatar(file);
      setAvatarUrl(stored.downloadUrl);
      setStatus('Avatar in Firebase Storage hochgeladen. Speichern nicht vergessen.');
    } catch (error) {
      setStatus((error as Error)?.message ?? 'Avatar konnte nicht hochgeladen werden.');
    } finally {
      event.target.value = '';
      setAvatarBusy(false);
    }
  };

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
        subtitle="Passe Avatar, Auth-Provider und Passwort fuer deinen Firebase-Workspace an."
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
          <div className="stack" style={{ flex: 1, minWidth: 220 }}>
            <div className="ai-chip-group">
              {(user?.highlights ?? []).map((chip) => (
                <span key={chip} className="chip">
                  {chip}
                </span>
              ))}
              {(user?.providers ?? []).map((provider) => (
                <span key={provider} className="chip chip--ghost">
                  {provider}
                </span>
              ))}
            </div>
            <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
              <GradientButton
                type="button"
                label="Avatar hochladen"
                busy={avatarBusy}
                busyLabel="Lade hoch..."
                onClick={() => avatarInputRef.current?.click()}
              />
              <input
                ref={avatarInputRef}
                type="file"
                accept="image/*"
                style={{ display: 'none' }}
                onChange={handleAvatarUpload}
              />
              {!firebaseConfigured && (
                <span className="chip chip--ghost">Firebase nicht konfiguriert</span>
              )}
            </div>
          </div>
        </div>
        <InputField
          label="Avatar URL"
          placeholder="https://storage.googleapis.com/..."
          value={avatarUrl}
          onChange={(event) => setAvatarUrl(event.target.value)}
          hint="Du kannst den Avatar direkt hochladen oder eine bestehende URL eintragen."
        />
        <div className="stack">
          <InputField
            label="Aktuelles Passwort"
            type="password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
            disabled={!canChangePassword}
            hint={
              canChangePassword
                ? 'Nur fuer E-Mail/Passwort-Konten erforderlich.'
                : 'Dieses Konto nutzt keinen Passwort-Provider.'
            }
          />
          <InputField
            label="Neues Passwort"
            type="password"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            disabled={!canChangePassword}
          />
        </div>
        <GradientButton
          type="submit"
          label="Profil speichern"
          busy={busy}
          busyLabel="Speichere Profil..."
        />
        {status && (
          <div
            className={`status-banner ${
              status === 'Profil aktualisiert.' ||
              status.includes('hochgeladen')
                ? 'status-banner--success'
                : 'status-banner--error'
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

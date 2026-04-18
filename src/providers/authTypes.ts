export type AuthUser = {
  uid: string;
  email: string;
  displayName?: string;
  avatarUrl?: string;
  highlights: string[];
  providers: string[];
};

export interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  firebaseConfigured: boolean;
  login: (email: string, password: string) => Promise<string | null>;
  register: (email: string, password: string) => Promise<string | null>;
  loginWithGoogle: () => Promise<string | null>;
  resetPassword: (email: string) => Promise<string>;
  updateProfile: (options: {
    avatarUrl?: string;
    currentPassword?: string;
    newPassword?: string;
  }) => Promise<string | null>;
  logout: () => void;
}

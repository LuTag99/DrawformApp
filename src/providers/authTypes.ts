export type AuthUser = {
  email: string;
  avatarUrl?: string;
  highlights: string[];
};

export type Credentials = {
  email: string;
  password: string;
  avatarUrl?: string;
  highlights: string[];
};

export interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<string | null>;
  register: (email: string, password: string) => Promise<string | null>;
  resetPassword: (email: string) => Promise<string>;
  updateProfile: (options: {
    avatarUrl?: string;
    currentPassword?: string;
    newPassword?: string;
  }) => Promise<string | null>;
  logout: () => void;
}

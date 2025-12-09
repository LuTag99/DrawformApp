import { createContext } from 'react';
import type { AuthContextValue } from './authTypes';

export const AuthContext = createContext<AuthContextValue | undefined>(
  undefined,
);

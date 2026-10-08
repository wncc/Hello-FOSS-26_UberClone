import * as SecureStore from 'expo-secure-store';
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import { Api, ApiError } from './api';
import { APP_VARIANT, apiBaseUrl, wsUrl } from './config';
import { RideSocket } from './socket';
import type { ServerEvent, User } from './types';

const ACCESS_KEY = 'auth.access';
const REFRESH_KEY = 'auth.refresh';

interface Session {
  ready: boolean;
  user: User | null;
  api: Api;
  socketConnected: boolean;
  signIn: (phone: string, code: string) => Promise<void>;
  signOut: () => Promise<void>;
  setUser: (user: User) => void;
  /** Subscribe to live server events; returns an unsubscribe function. */
  onEvent: (handler: (e: ServerEvent) => void) => () => void;
  /** Send over the live socket; false if it isn't connected. */
  sendLive: (message: object) => boolean;
}

const SessionContext = createContext<Session | null>(null);

/** Tokens live in SecureStore and in memory; one API client and one socket per app run. */
class AuthCore {
  access: string | null = null;
  refreshToken: string | null = null;
  readonly api: Api;
  readonly socket: RideSocket;

  constructor(onSocketStatus: (connected: boolean) => void, private onSignedOut: () => void) {
    this.api = new Api(apiBaseUrl(), { access: () => this.access, refresh: () => this.refreshAccess() });
    this.socket = new RideSocket({
      url: () => (this.access ? wsUrl(this.access) : null),
      onStatus: onSocketStatus,
      onAuthError: async () => {
        if (await this.refreshAccess()) this.socket.start();
      },
    });
  }

  async load(): Promise<void> {
    [this.access, this.refreshToken] = await Promise.all([
      SecureStore.getItemAsync(ACCESS_KEY), SecureStore.getItemAsync(REFRESH_KEY)]);
  }

  async store(access: string, refresh: string): Promise<void> {
    this.access = access;
    this.refreshToken = refresh;
    await Promise.all([SecureStore.setItemAsync(ACCESS_KEY, access), SecureStore.setItemAsync(REFRESH_KEY, refresh)]);
  }

  async clear(): Promise<void> {
    this.socket.stop();
    this.access = this.refreshToken = null;
    await Promise.all([SecureStore.deleteItemAsync(ACCESS_KEY), SecureStore.deleteItemAsync(REFRESH_KEY)]);
  }

  async refreshAccess(): Promise<string | null> {
    if (!this.refreshToken) return null;
    try {
      const tokens = await this.api.refresh(this.refreshToken);
      await this.store(tokens.access_token, tokens.refresh_token);
      return tokens.access_token;
    } catch {
      await this.clear();
      this.onSignedOut();
      return null;
    }
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const [socketConnected, setSocketConnected] = useState(false);
  const core = useMemo(() => new AuthCore(setSocketConnected, () => setUser(null)), []);

  // Restore a saved session on launch.
  useEffect(() => {
    (async () => {
      await core.load();
      if (core.access) {
        try {
          const me = await core.api.me();
          if (me.role === APP_VARIANT || me.role === 'admin') setUser(me);
          else await core.clear();
        } catch (e) {
          if (e instanceof ApiError && e.status === 401) await core.clear();
          // Network errors: stay logged out of the UI but keep tokens; the user can retry.
        }
      }
      setReady(true);
    })();
  }, [core]);

  const userId = user?.id;
  useEffect(() => {
    if (!userId) return;
    core.socket.start();
    return () => core.socket.stop();
  }, [userId, core]);

  const value = useMemo<Session>(() => ({
    ready,
    user,
    api: core.api,
    socketConnected,
    signIn: async (phone, code) => {
      const tokens = await core.api.verifyOtp(phone, code, APP_VARIANT);
      await core.store(tokens.access_token, tokens.refresh_token);
      setUser(tokens.user);
    },
    signOut: async () => {
      await core.clear();
      setUser(null);
    },
    setUser,
    onEvent: (handler) => core.socket.on(handler),
    sendLive: (message) => core.socket.send(message),
  }), [ready, user, socketConnected, core]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error('useSession must be used inside SessionProvider');
  return ctx;
}

/** Run `handler` for every live event while the component is mounted. */
export function useServerEvents(handler: (e: ServerEvent) => void): void {
  const { onEvent } = useSession();
  const latest = useRef(handler);
  useEffect(() => {
    latest.current = handler;
  });
  useEffect(() => onEvent((e) => latest.current(e)), [onEvent]);
}

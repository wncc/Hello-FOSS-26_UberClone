import type { ServerEvent } from './types';

type Handler = (event: ServerEvent) => void;

export interface SocketOptions {
  /** Returns the URL to connect to, or null if not logged in. Called on every (re)connect. */
  url: () => string | null;
  WebSocketImpl?: typeof WebSocket;
  minBackoffMs?: number;
  maxBackoffMs?: number;
  keepAliveMs?: number;
  onStatus?: (connected: boolean) => void;
  onAuthError?: () => void;
}

const AUTH_CLOSE_CODE = 4401;

/** One live connection per logged-in user; reconnects with exponential backoff. */
export class RideSocket {
  private ws: WebSocket | null = null;
  private handlers = new Set<Handler>();
  private attempts = 0;
  private stopped = true;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private keepAliveTimer: ReturnType<typeof setInterval> | null = null;

  constructor(private opts: SocketOptions) {}

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.clearTimers();
    this.ws?.close();
    this.ws = null;
  }

  on(handler: Handler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  /** Returns false if not connected (callers fall back to HTTP). */
  send(message: object): boolean {
    if (this.ws?.readyState !== 1) return false;
    this.ws.send(JSON.stringify(message));
    return true;
  }

  get connected(): boolean {
    return this.ws?.readyState === 1;
  }

  private connect(): void {
    const url = this.opts.url();
    if (this.stopped || !url) return;
    const Impl = this.opts.WebSocketImpl ?? WebSocket;
    const ws = new Impl(url);
    this.ws = ws;

    ws.onopen = () => {
      this.attempts = 0;
      this.opts.onStatus?.(true);
      this.keepAliveTimer = setInterval(() => this.send({ type: 'ping' }), this.opts.keepAliveMs ?? 25_000);
    };
    ws.onmessage = (msg) => {
      let event: ServerEvent;
      try {
        event = JSON.parse(String(msg.data));
      } catch {
        return;
      }
      this.handlers.forEach((h) => h(event));
    };
    ws.onclose = (e) => {
      this.clearTimers();
      this.opts.onStatus?.(false);
      if (this.ws === ws) this.ws = null;
      if (e.code === AUTH_CLOSE_CODE) {
        this.opts.onAuthError?.();
        return;
      }
      this.scheduleReconnect();
    };
    ws.onerror = () => ws.close();
  }

  private scheduleReconnect(): void {
    if (this.stopped) return;
    const min = this.opts.minBackoffMs ?? 1000;
    const max = this.opts.maxBackoffMs ?? 15_000;
    const delay = Math.min(max, min * 2 ** this.attempts);
    this.attempts += 1;
    this.retryTimer = setTimeout(() => this.connect(), delay);
  }

  private clearTimers(): void {
    if (this.retryTimer) clearTimeout(this.retryTimer);
    if (this.keepAliveTimer) clearInterval(this.keepAliveTimer);
    this.retryTimer = this.keepAliveTimer = null;
  }
}

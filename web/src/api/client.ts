// JSON-RPC 2.0 client for the Python server, over WebSocket.
//
// The session token arrives in the initial URL (`?t=…`). It is presented in two different ways
// depending on the channel, because the browser APIs leave no choice:
//   - WebSocket: as a query parameter (the WebSocket API allows no custom header);
//   - fetch    : as an X-Retina-Token header, which crosses the Vite proxy in development where
//                the cookie would not follow (origin :5173 ≠ origin :8765).
// See python/retina/server/security.py for the other end.

import { m } from '../paraglide/messages';

export type RpcId = number;

interface RpcResponse {
  jsonrpc: '2.0';
  id: RpcId | null;
  result?: unknown;
  error?: { code: number; message: string; data?: unknown };
}

interface RpcNotification {
  jsonrpc: '2.0';
  method: string;
  params?: unknown;
}

export type ConnectionState = 'connecting' | 'open' | 'closed';

type NotificationHandler = (method: string, params: unknown) => void;
type StateHandler = (state: ConnectionState) => void;

export class RpcError extends Error {
  constructor(
    readonly code: number,
    message: string,
    readonly data?: unknown,
  ) {
    super(message);
    this.name = 'RpcError';
  }
}

function readToken(): string {
  const fromUrl = new URLSearchParams(location.search).get('t');
  if (fromUrl) {
    sessionStorage.setItem('retina.token', fromUrl);
    // Strip the token from the address bar: it has no business in the history.
    history.replaceState(null, '', location.pathname);
    return fromUrl;
  }
  return sessionStorage.getItem('retina.token') ?? '';
}

export class RetinaClient {
  readonly token = readToken();
  /** Identity assigned by the server at `hello` — see Hello.connection. */
  connectionId: string | null = null;
  /** Server process identifier (`hello.run`) — see {@link scoped}. */
  run: string | null = null;
  private ws: WebSocket | null = null;
  private nextId: RpcId = 1;
  private readonly pending = new Map<RpcId, { resolve: (v: unknown) => void; reject: (e: Error) => void }>();
  private readonly notificationHandlers = new Set<NotificationHandler>();
  private readonly stateHandlers = new Set<StateHandler>();
  private reconnectDelay = 500;
  private closedByUser = false;

  connect(): void {
    this.closedByUser = false;
    this.setState('connecting');
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${scheme}://${location.host}/ws?t=${encodeURIComponent(this.token)}`);
    this.ws = ws;

    ws.addEventListener('open', () => {
      this.reconnectDelay = 500;
      this.setState('open');
    });

    ws.addEventListener('message', (event: MessageEvent<string>) => {
      this.onMessage(event.data);
    });

    ws.addEventListener('close', () => {
      this.setState('closed');
      // Every in-flight request is lost: reject it rather than leave it hanging.
      for (const [, entry] of this.pending) {
        entry.reject(new Error(m.error_connection_closed()));
      }
      this.pending.clear();
      if (!this.closedByUser) {
        setTimeout(() => this.connect(), this.reconnectDelay);
        this.reconnectDelay = Math.min(this.reconnectDelay * 2, 5000);
      }
    });
  }

  disconnect(): void {
    this.closedByUser = true;
    this.ws?.close();
  }

  private setState(state: ConnectionState): void {
    for (const handler of this.stateHandlers) handler(state);
  }

  private onMessage(raw: string): void {
    let message: RpcResponse | RpcNotification;
    try {
      message = JSON.parse(raw) as RpcResponse | RpcNotification;
    } catch {
      console.error('message serveur illisible', raw);
      return;
    }

    if ('method' in message) {
      for (const handler of this.notificationHandlers) {
        handler(message.method, message.params);
      }
      return;
    }

    if (message.id === null) return;
    const entry = this.pending.get(message.id);
    if (!entry) return;
    this.pending.delete(message.id);
    if (message.error) {
      entry.reject(new RpcError(message.error.code, message.error.message, message.error.data));
    } else {
      entry.resolve(message.result);
    }
  }

  call<T = unknown>(method: string, params?: unknown): Promise<T> {
    const ws = this.ws;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      return Promise.reject(new Error(m.error_server_unreachable({ method })));
    }
    const id = this.nextId++;
    const payload = params === undefined
      ? { jsonrpc: '2.0', id, method }
      : { jsonrpc: '2.0', id, method, params };
    ws.send(JSON.stringify(payload));
    return new Promise<T>((resolve, reject) => {
      this.pending.set(id, { resolve: resolve as (v: unknown) => void, reject });
    });
  }

  onNotification(handler: NotificationHandler): () => void {
    this.notificationHandlers.add(handler);
    return () => this.notificationHandlers.delete(handler);
  }

  onStateChange(handler: StateHandler): () => void {
    this.stateHandlers.add(handler);
    return () => this.stateHandlers.delete(handler);
  }

  /** Authenticated HTTP request — pixels, docs, icons. */
  async fetch(path: string, init?: RequestInit): Promise<Response> {
    const headers = new Headers(init?.headers);
    headers.set('X-Retina-Token', this.token);
    return fetch(this.scoped(path), { ...init, headers });
  }

  /**
   * Adds the current run identifier to **pixel** URLs.
   *
   * `/api/pixels/Image01.f16?gen=1` does not designate the same image from one session to the
   * next: view ids and generations both restart at 1. Yet the versions shipped before this fix
   * served that URL as `immutable, max-age=1 year`, and the WebView2 **disk** cache survives
   * restarts — so it replayed the previous session's pixels, `texImage2D` failed on stale
   * dimensions, and the viewport stayed black.
   *
   * The server no longer revalidates (see `pixels.py`), but that is not enough: an already
   * stored entry is *fresh for a year* and the browser does not even contact it again.
   * Changing the URL is the only way to cure existing installations — hence this `run`, which
   * the server ignores and whose only purpose is to never land on them again.
   *
   * It is done here, and not at each call site, so that no site can forget it.
   */
  private scoped(path: string): string {
    if (!this.run || !path.startsWith('/api/') || !path.includes('.f16')) return path;
    return `${path}${path.includes('?') ? '&' : '?'}run=${encodeURIComponent(this.run)}`;
  }
}

export const client = new RetinaClient();

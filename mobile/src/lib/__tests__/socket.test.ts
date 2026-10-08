import { afterEach, beforeEach, expect, jest, test } from '@jest/globals';
import { RideSocket } from '../socket';

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  receive(obj: unknown) {
    this.onmessage?.({ data: JSON.stringify(obj) });
  }
  send(data: string) {
    this.sent.push(data);
  }
  close(code = 1006) {
    this.readyState = 3;
    this.onclose?.({ code });
  }
}

const sockets: RideSocket[] = [];

function make(opts: Partial<ConstructorParameters<typeof RideSocket>[0]> = {}) {
  const s = new RideSocket({
    url: () => 'ws://test/ws?token=t',
    WebSocketImpl: FakeWebSocket as unknown as typeof WebSocket,
    minBackoffMs: 100,
    maxBackoffMs: 400,
    keepAliveMs: 1000,
    ...opts,
  });
  sockets.push(s);
  return s;
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  jest.useFakeTimers();
});
afterEach(() => {
  sockets.splice(0).forEach((s) => s.stop());
  jest.useRealTimers();
});

test('delivers events to subscribers and sends when open', () => {
  const s = make();
  const got: string[] = [];
  const off = s.on((e) => got.push(e.event));
  s.start();
  const ws = FakeWebSocket.instances[0];
  expect(s.send({ type: 'location' })).toBe(false);   // not open yet
  ws.open();
  expect(s.send({ type: 'location', lat: 1, lng: 2 })).toBe(true);
  ws.receive({ event: 'ride:ping', data: {} });
  off();
  ws.receive({ event: 'ride:taken', data: {} });
  expect(got).toEqual(['ride:ping']);
});

test('reconnects with capped exponential backoff', () => {
  const s = make();
  s.start();
  FakeWebSocket.instances[0].close();
  jest.advanceTimersByTime(99);
  expect(FakeWebSocket.instances).toHaveLength(1);
  jest.advanceTimersByTime(1);
  expect(FakeWebSocket.instances).toHaveLength(2);
  FakeWebSocket.instances[1].close();
  jest.advanceTimersByTime(200);
  expect(FakeWebSocket.instances).toHaveLength(3);
  FakeWebSocket.instances[2].close();
  jest.advanceTimersByTime(400);
  FakeWebSocket.instances[3].close();
  jest.advanceTimersByTime(400);                       // capped at maxBackoffMs
  expect(FakeWebSocket.instances).toHaveLength(5);
  FakeWebSocket.instances[4].open();                    // a successful connect resets the backoff
  FakeWebSocket.instances[4].close();
  jest.advanceTimersByTime(100);
  expect(FakeWebSocket.instances).toHaveLength(6);
});

test('stops on auth rejection and when stopped', () => {
  const onAuthError = jest.fn();
  const s = make({ onAuthError });
  s.start();
  FakeWebSocket.instances[0].close(4401);
  jest.advanceTimersByTime(5000);
  expect(onAuthError).toHaveBeenCalled();
  expect(FakeWebSocket.instances).toHaveLength(1);

  const t = make();
  t.start();
  t.stop();
  jest.advanceTimersByTime(5000);
  expect(FakeWebSocket.instances).toHaveLength(2);
});

test('keep-alive pings while open', () => {
  const s = make();
  s.start();
  const ws = FakeWebSocket.instances[0];
  ws.open();
  jest.advanceTimersByTime(2000);
  expect(ws.sent.map((m) => JSON.parse(m).type)).toEqual(['ping', 'ping']);
});

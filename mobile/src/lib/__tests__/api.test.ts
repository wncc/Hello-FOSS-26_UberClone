import { expect, jest, test } from '@jest/globals';
import { Api, ApiError } from '../api';

function response(status: number, body?: unknown): Response {
  return { status, ok: status >= 200 && status < 300, text: async () => (body === undefined ? '' : JSON.stringify(body)) } as Response;
}

test('sends bearer token and JSON body', async () => {
  const fetchImpl = jest.fn(async () => response(200, { id: 'U1' }));
  const api = new Api('http://x', { access: () => 'tok', refresh: async () => null }, fetchImpl as unknown as typeof fetch);
  await api.updateName('Asha');
  const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe('http://x/me');
  expect(init.method).toBe('PATCH');
  expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok');
  expect(JSON.parse(String(init.body))).toEqual({ name: 'Asha' });
});

test('refreshes once on 401 and retries', async () => {
  let token = 'old';
  const fetchImpl = jest.fn<typeof fetch>()
    .mockResolvedValueOnce(response(401, { detail: 'expired' }))
    .mockResolvedValueOnce(response(200, { id: 'U1' }));
  const refresh = jest.fn(async () => {
    token = 'new';
    return token;
  });
  const api = new Api('http://x', { access: () => token, refresh }, fetchImpl as unknown as typeof fetch);
  await expect(api.me()).resolves.toEqual({ id: 'U1' });
  expect(refresh).toHaveBeenCalledTimes(1);
  expect(((fetchImpl.mock.calls[1] as unknown as [string, RequestInit])[1].headers as Record<string, string>).Authorization).toBe('Bearer new');
});

test('surfaces server and validation messages', async () => {
  const api = new Api('http://x', { access: () => null, refresh: async () => null },
    jest.fn<typeof fetch>()
      .mockResolvedValueOnce(response(409, { detail: 'you already have an active ride' }))
      .mockResolvedValueOnce(response(422, { detail: [{ msg: 'field required' }] })) as unknown as typeof fetch);
  await expect(api.activeRide()).rejects.toEqual(new ApiError(409, 'you already have an active ride'));
  await expect(api.activeRide()).rejects.toThrow('field required');
});

test('network failure and empty 204', async () => {
  const down = new Api('http://x', { access: () => null, refresh: async () => null },
    jest.fn(async () => { throw new TypeError('Network request failed'); }) as unknown as typeof fetch);
  await expect(down.me()).rejects.toMatchObject({ status: 0 });
  const ok = new Api('http://x', { access: () => null, refresh: async () => null },
    jest.fn(async () => response(204)) as unknown as typeof fetch);
  await expect(ok.reject('R1')).resolves.toBeUndefined();
});

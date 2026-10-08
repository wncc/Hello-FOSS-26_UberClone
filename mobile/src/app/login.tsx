import { useState } from 'react';
import { KeyboardAvoidingView, Platform, View } from 'react-native';

import { Body, Button, ErrorText, Input, Screen, Title, space } from '@/components/ui';
import { ApiError } from '@/lib/api';
import { APP_VARIANT } from '@/lib/config';
import { normalizeIndianPhone } from '@/lib/format';
import { useSession } from '@/lib/session';

export default function Login() {
  const { api, signIn } = useSession();
  const [phone, setPhone] = useState('');
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [code, setCode] = useState('');
  const [devCode, setDevCode] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function sendCode() {
    const normalized = normalizeIndianPhone(phone);
    if (!normalized) {
      setError('Enter a valid 10-digit mobile number');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await api.requestOtp(normalized);
      setSentTo(normalized);
      setDevCode(res.dev_code);
      if (res.dev_code) setCode(res.dev_code);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Something went wrong');
    } finally {
      setBusy(false);
    }
  }

  async function verify() {
    if (!sentTo) return;
    setBusy(true);
    setError(null);
    try {
      await signIn(sentTo, code.trim());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Something went wrong');
      setBusy(false);
    }
  }

  return (
    <Screen>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1, justifyContent: 'center', gap: space.lg }}>
        <View style={{ gap: space.sm }}>
          <Title>{APP_VARIANT === 'driver' ? 'Drive with us' : 'Get a ride'}</Title>
          <Body muted>{sentTo ? `Enter the code sent to ${sentTo}` : 'Log in with your mobile number'}</Body>
        </View>
        {sentTo ? (
          <>
            <Input label="Verification code" value={code} onChangeText={setCode} keyboardType="number-pad"
                   maxLength={6} autoFocus />
            {devCode ? <Body muted>Development mode: the code is {devCode}</Body> : null}
            <ErrorText message={error} />
            <Button title="Verify" onPress={verify} loading={busy} disabled={code.trim().length < 4} />
            <Button title="Change number" kind="secondary" onPress={() => { setSentTo(null); setCode(''); setError(null); }} />
          </>
        ) : (
          <>
            <Input label="Mobile number" value={phone} onChangeText={setPhone} keyboardType="phone-pad"
                   placeholder="98450 12345" maxLength={14} autoFocus />
            <ErrorText message={error} />
            <Button title="Send code" onPress={sendCode} loading={busy} />
          </>
        )}
      </KeyboardAvoidingView>
    </Screen>
  );
}

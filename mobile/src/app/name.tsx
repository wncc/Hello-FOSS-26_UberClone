import { useState } from 'react';
import { View } from 'react-native';

import { Body, Button, ErrorText, Input, Screen, Title, space } from '@/components/ui';
import { ApiError } from '@/lib/api';
import { useSession } from '@/lib/session';

export default function Name() {
  const { api, setUser, signOut } = useSession();
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      setUser(await api.updateName(name.trim()));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Something went wrong');
      setBusy(false);
    }
  }

  return (
    <Screen style={{ justifyContent: 'center', gap: space.lg }}>
      <View style={{ gap: space.sm }}>
        <Title>What’s your name?</Title>
        <Body muted>Shown to the other person on each ride.</Body>
      </View>
      <Input value={name} onChangeText={setName} placeholder="Full name" autoFocus maxLength={80} />
      <ErrorText message={error} />
      <Button title="Continue" onPress={save} loading={busy} disabled={!name.trim()} />
      <Button title="Log out" kind="secondary" onPress={signOut} />
    </Screen>
  );
}

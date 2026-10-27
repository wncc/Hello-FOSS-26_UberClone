
import { useState } from 'react';
import { View } from 'react-native';

import { Body, Button, ErrorText, Input, Screen, Title, space } from '@/components/ui';
import { ApiError } from '@/lib/api';
import { useLanguage } from '@/lib/i18n';
import { useSession } from '@/lib/session';

export default function Name() {
  const { api, setUser, signOut } = useSession();
  const { t } = useLanguage();
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      setUser(await api.updateName(name.trim()));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('somethingWentWrong'));
      setBusy(false);
    }
  }

  return (
    <Screen style={{ justifyContent: 'center', gap: space.lg }}>
      <View style={{ gap: space.sm }}>
        <Title>{t('yourName')}</Title>
        <Body muted>{t('nameHint')}</Body>
      </View>
      <Input
        value={name}
        onChangeText={setName}
        placeholder={t('fullName')}
        autoFocus
        maxLength={80}
      />
      <ErrorText message={error} />
      <Button
        title={t('continue')}
        onPress={save}
        loading={busy}
        disabled={!name.trim()}
      />
      <Button title={t('logout')} kind="secondary" onPress={signOut} />
    </Screen>
  );
}

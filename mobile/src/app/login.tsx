import { useState } from 'react';
import { KeyboardAvoidingView, Platform, View } from 'react-native';

import { Body, Button, ErrorText, Input, Screen, Title, space } from '@/components/ui';
import { LanguagePicker } from '@/components/LanguagePicker';
import { ApiError } from '@/lib/api';
import { APP_VARIANT } from '@/lib/config';
import { normalizeIndianPhone } from '@/lib/format';
import { useLanguage } from '@/lib/i18n';
import { useSession } from '@/lib/session';

export default function Login() {
  const { api, signIn } = useSession();
  const { t } = useLanguage();

  const [phone, setPhone] = useState('');
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [code, setCode] = useState('');
  const [devCode, setDevCode] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function sendCode() {
    const normalized = normalizeIndianPhone(phone);
    if (!normalized) {
      setError(t('validPhone'));
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
      setError(e instanceof ApiError ? e.message : t('somethingWentWrong'));
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
      setError(e instanceof ApiError ? e.message : t('somethingWentWrong'));
      setBusy(false);
    }
  }

  return (
    <Screen>
      <LanguagePicker />

      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={{ flex: 1, justifyContent: 'center', gap: space.lg }}
      >
        <View style={{ gap: space.sm }}>
          <Title>
            {APP_VARIANT === 'driver' ? t('driveWithUs') : t('getRide')}
          </Title>
          <Body muted>
            {sentTo
              ? t('codeSentTo', { phone: sentTo })
              : t('loginPhone')}
          </Body>
        </View>

        {sentTo ? (
          <>
            <Input
              label={t('verificationCode')}
              value={code}
              onChangeText={setCode}
              keyboardType="number-pad"
              maxLength={6}
              autoFocus
            />

            {devCode ? (
              <Body muted>
                {t('developmentCode', { code: devCode })}
              </Body>
            ) : null}

            <ErrorText message={error} />

            <Button
              title={t('verify')}
              onPress={verify}
              loading={busy}
              disabled={code.trim().length < 4}
            />

            <Button
              title={t('changeNumber')}
              kind="secondary"
              onPress={() => {
                setSentTo(null);
                setCode('');
                setError(null);
              }}
            />
          </>
        ) : (
          <>
            <Input
              label={t('mobileNumber')}
              value={phone}
              onChangeText={setPhone}
              keyboardType="phone-pad"
              placeholder="98450 12345"
              maxLength={14}
              autoFocus
            />

            <ErrorText message={error} />

            <Button
              title={t('sendCode')}
              onPress={sendCode}
              loading={busy}
            />
          </>
        )}
      </KeyboardAvoidingView>
    </Screen>
  );
}
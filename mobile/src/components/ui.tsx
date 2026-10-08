import type { ReactNode } from 'react';
import {
  ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View, type StyleProp, type TextInputProps,
  type TextProps, type TextStyle, type ViewStyle,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

export const colors = {
  bg: '#FFFFFF',
  surface: '#F3F4F6',
  border: '#E5E7EB',
  text: '#111827',
  muted: '#6B7280',
  primary: '#111827',
  primaryText: '#FFFFFF',
  accent: '#10B981',
  danger: '#DC2626',
  warning: '#F59E0B',
};

export const space = { xs: 4, sm: 8, md: 16, lg: 24, xl: 32 };

export function Screen({ children, style, padded = true }: { children: ReactNode; style?: StyleProp<ViewStyle>; padded?: boolean }) {
  return (
    <SafeAreaView style={[styles.screen, padded && { padding: space.md }, style]} edges={['top', 'bottom']}>
      {children}
    </SafeAreaView>
  );
}

export function Title({ children, style }: { children: ReactNode; style?: StyleProp<TextStyle> }) {
  return <Text style={[styles.title, style]}>{children}</Text>;
}

export function Body({ children, muted, style, ...rest }: TextProps & { muted?: boolean }) {
  return <Text style={[styles.body, muted && { color: colors.muted }, style]} {...rest}>{children}</Text>;
}

export function ErrorText({ message }: { message: string | null }) {
  return message ? <Text style={styles.error}>{message}</Text> : null;
}

type ButtonKind = 'primary' | 'secondary' | 'danger' | 'accent';

export function Button({ title, onPress, kind = 'primary', loading, disabled, style }: {
  title: string;
  onPress: () => void;
  kind?: ButtonKind;
  loading?: boolean;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  const bg = { primary: colors.primary, secondary: colors.surface, danger: colors.danger, accent: colors.accent }[kind];
  const fg = kind === 'secondary' ? colors.text : colors.primaryText;
  const off = disabled || loading;
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      disabled={off}
      style={({ pressed }) => [styles.button, { backgroundColor: bg, opacity: off ? 0.5 : pressed ? 0.8 : 1 }, style]}>
      {loading ? <ActivityIndicator color={fg} /> : <Text style={[styles.buttonText, { color: fg }]}>{title}</Text>}
    </Pressable>
  );
}

export function Input(props: TextInputProps & { label?: string }) {
  const { label, style, ...rest } = props;
  return (
    <View style={{ gap: space.xs }}>
      {label ? <Text style={styles.label}>{label}</Text> : null}
      <TextInput placeholderTextColor={colors.muted} style={[styles.input, style]} {...rest} />
    </View>
  );
}

export function Card({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[styles.card, style]}>{children}</View>;
}

/** Bottom sheet-like panel over a full-screen map. */
export function Sheet({ children }: { children: ReactNode }) {
  return (
    <SafeAreaView edges={['bottom']} style={styles.sheet}>
      {children}
    </SafeAreaView>
  );
}

export function Row({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[styles.row, style]}>{children}</View>;
}

export function Loading() {
  return (
    <View style={styles.center}>
      <ActivityIndicator size="large" color={colors.primary} />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  title: { fontSize: 24, fontWeight: '700', color: colors.text },
  body: { fontSize: 16, color: colors.text },
  label: { fontSize: 14, color: colors.muted },
  error: { color: colors.danger, fontSize: 14 },
  button: { minHeight: 52, borderRadius: 12, alignItems: 'center', justifyContent: 'center', paddingHorizontal: space.md },
  buttonText: { fontSize: 17, fontWeight: '600' },
  input: {
    minHeight: 52, borderRadius: 12, borderWidth: 1, borderColor: colors.border, paddingHorizontal: space.md,
    fontSize: 17, color: colors.text, backgroundColor: colors.bg,
  },
  card: { borderRadius: 14, backgroundColor: colors.surface, padding: space.md, gap: space.sm },
  sheet: {
    position: 'absolute', left: 0, right: 0, bottom: 0, backgroundColor: colors.bg, padding: space.md, gap: space.md,
    borderTopLeftRadius: 20, borderTopRightRadius: 20, shadowColor: '#000', shadowOpacity: 0.15, shadowRadius: 12,
    elevation: 12,
  },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.bg },
});

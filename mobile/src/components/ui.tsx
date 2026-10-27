import { useMemo, type ReactNode } from 'react';
import {
  ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View, useColorScheme, type StyleProp,
  type TextInputProps, type TextProps, type TextStyle, type ViewStyle,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { paletteFor, type Palette } from '@/lib/theme';

export type { Palette };

export const space = { xs: 4, sm: 8, md: 16, lg: 24, xl: 32 };

/** The active palette; re-renders when the phone switches between light and dark. */
export function useTheme(): Palette {
  return paletteFor(useColorScheme());
}

/**
 * Styles that depend on the palette: `const useStyles = themed((t) => StyleSheet.create({...}))`,
 * then `const styles = useStyles()` in the component. Rebuilt only when the theme changes.
 */
export function themed<T>(build: (t: Palette) => T): () => T {
  return function useStyles() {
    const t = useTheme();
    return useMemo(() => build(t), [t]);
  };
}

export function Screen({ children, style, padded = true }: { children: ReactNode; style?: StyleProp<ViewStyle>; padded?: boolean }) {
  const styles = useStyles();
  return (
    <SafeAreaView style={[styles.screen, padded && { padding: space.md }, style]} edges={['top', 'bottom']}>
      {children}
    </SafeAreaView>
  );
}

export function Title({ children, style }: { children: ReactNode; style?: StyleProp<TextStyle> }) {
  const styles = useStyles();
  return <Text style={[styles.title, style]}>{children}</Text>;
}

export function Body({ children, muted, style, ...rest }: TextProps & { muted?: boolean }) {
  const styles = useStyles();
  const t = useTheme();
  return <Text style={[styles.body, muted && { color: t.muted }, style]} {...rest}>{children}</Text>;
}

export function ErrorText({ message }: { message: string | null }) {
  const styles = useStyles();
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
  const styles = useStyles();
  const t = useTheme();
  const bg = { primary: t.primary, secondary: t.surface, danger: t.danger, accent: t.accent }[kind];
  const fg = kind === 'secondary' ? t.text : t.primaryText;
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
  const styles = useStyles();
  const t = useTheme();
  const scheme = useColorScheme();
  return (
    <View style={{ gap: space.xs }}>
      {label ? <Text style={styles.label}>{label}</Text> : null}
      <TextInput placeholderTextColor={t.muted} keyboardAppearance={scheme === 'dark' ? 'dark' : 'light'}
                 style={[styles.input, style]} {...rest} />
    </View>
  );
}

export function Card({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  const styles = useStyles();
  return <View style={[styles.card, style]}>{children}</View>;
}

/** Bottom sheet-like panel over a full-screen map. */
export function Sheet({ children }: { children: ReactNode }) {
  const styles = useStyles();
  return (
    <SafeAreaView edges={['bottom']} style={styles.sheet}>
      {children}
    </SafeAreaView>
  );
}

export function Row({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  const styles = useStyles();
  return <View style={[styles.row, style]}>{children}</View>;
}

export function Loading() {
  const styles = useStyles();
  const t = useTheme();
  return (
    <View style={styles.center}>
      <ActivityIndicator size="large" color={t.primary} />
    </View>
  );
}

const useStyles = themed((t) => StyleSheet.create({
  screen: { flex: 1, backgroundColor: t.bg },
  title: { fontSize: 24, fontWeight: '700', color: t.text },
  body: { fontSize: 16, color: t.text },
  label: { fontSize: 14, color: t.muted },
  error: { color: t.danger, fontSize: 14 },
  button: { minHeight: 52, borderRadius: 12, alignItems: 'center', justifyContent: 'center', paddingHorizontal: space.md },
  buttonText: { fontSize: 17, fontWeight: '600' },
  input: {
    minHeight: 52, borderRadius: 12, borderWidth: 1, borderColor: t.border, paddingHorizontal: space.md,
    fontSize: 17, color: t.text, backgroundColor: t.bg,
  },
  card: { borderRadius: 14, backgroundColor: t.surface, padding: space.md, gap: space.sm },
  sheet: {
    position: 'absolute', left: 0, right: 0, bottom: 0, backgroundColor: t.bg, padding: space.md, gap: space.md,
    borderTopLeftRadius: 20, borderTopRightRadius: 20, shadowColor: '#000', shadowOpacity: 0.15, shadowRadius: 12,
    elevation: 12,
  },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: t.bg },
}));

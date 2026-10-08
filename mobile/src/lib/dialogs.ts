import { Alert, Platform } from 'react-native';

/** Ask before a destructive action. React Native's Alert does nothing in the browser, so use confirm() there. */
export function confirmAction(title: string, message: string, confirmText: string, onConfirm: () => void,
                              cancelText = 'Keep ride'): void {
  if (Platform.OS === 'web') {
    if (globalThis.confirm?.(`${title}\n\n${message}`)) onConfirm();
    return;
  }
  Alert.alert(title, message, [
    { text: cancelText, style: 'cancel' },
    { text: confirmText, style: 'destructive', onPress: onConfirm },
  ]);
}

export function notify(title: string, message: string): void {
  if (Platform.OS === 'web') globalThis.alert?.(`${title}\n\n${message}`);
  else Alert.alert(title, message);
}

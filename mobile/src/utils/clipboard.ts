/**
 * Copy text to the system clipboard. Uses React Native's core Clipboard,
 * which RN 0.81 still ships (deprecated, but its native module is part of
 * the core binary) — so this works over OTA without a new native build.
 * Switch to expo-clipboard when the next native build is cut.
 */
import { Clipboard } from 'react-native';

export function copyText(text: string): boolean {
  try {
    Clipboard.setString(text);
    return true;
  } catch {
    return false;
  }
}

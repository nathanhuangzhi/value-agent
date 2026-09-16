/** Small "copy" icon that flips to "Copied" for a moment after a press. */
import { Ionicons } from '@expo/vector-icons';
import { useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text } from 'react-native';

import { fontSize, spacing } from '@/theme/colors';
import { copyText } from '@/utils/clipboard';

export function CopyButton({ text, color }: { text: string; color: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  const onPress = () => {
    if (!copyText(text)) return;
    setCopied(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), 1500);
  };
  return (
    <Pressable onPress={onPress} hitSlop={8} style={styles.btn} accessibilityLabel="Copy message">
      <Ionicons name={copied ? 'checkmark' : 'copy-outline'} size={14} color={color} />
      {copied ? <Text style={[styles.label, { color }]}>Copied</Text> : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  btn: { flexDirection: 'row', alignItems: 'center', gap: 3, paddingLeft: spacing.sm, paddingVertical: 2 },
  label: { fontSize: fontSize.xs - 1 },
});

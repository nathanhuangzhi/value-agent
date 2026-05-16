import { ReactNode } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { useColors, fontSize, spacing } from '@/theme/colors';

export function Section({ title, children }: { title: string; children: ReactNode }) {
  const c = useColors();
  return (
    <View style={styles.wrap}>
      <Text style={[styles.title, { color: c.brand, borderBottomColor: c.brand }]}>
        {title.toUpperCase()}
      </Text>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    marginTop: spacing.xl,
    // Side padding matches the screen header (`paddingHorizontal: lg`)
    // so every section's content aligns to the same gutter.
    paddingHorizontal: spacing.lg,
  },
  title: {
    fontSize: fontSize.xs,
    fontWeight: '700',
    letterSpacing: 2,
    borderBottomWidth: 2,
    paddingBottom: 4,
    marginBottom: spacing.md,
  },
});

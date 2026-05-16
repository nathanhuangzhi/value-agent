import { StyleSheet, Text, View } from 'react-native';

import { useColors, radii, spacing, fontSize } from '@/theme/colors';
import type { ValidationStatus } from '@/api/types';

const LABEL: Record<ValidationStatus, string> = {
  ok: 'OK',
  info: 'INFO',
  warn: 'WARN',
  error: 'ERROR',
};

export function StatusBadge({ status }: { status: ValidationStatus }) {
  const c = useColors();
  const bgMap: Record<ValidationStatus, string> = {
    ok: c.statusOkBg,
    info: c.statusInfoBg,
    warn: c.statusWarnBg,
    error: c.statusErrorBg,
  };
  const textMap: Record<ValidationStatus, string> = {
    ok: c.statusOkText,
    info: c.statusInfoText,
    warn: c.statusWarnText,
    error: c.statusErrorText,
  };
  return (
    <View style={[styles.pill, { backgroundColor: bgMap[status] }]}>
      <Text style={[styles.label, { color: textMap[status] }]}>{LABEL[status]}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: radii.sm,
    alignSelf: 'flex-start',
  },
  label: {
    fontSize: fontSize.xs - 1,
    fontWeight: '700',
    letterSpacing: 1,
  },
});

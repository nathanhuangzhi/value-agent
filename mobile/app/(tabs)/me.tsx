/**
 * Me tab — the account: sign in / out today; custom metrics and charts
 * will live here next.
 */
import { Ionicons } from '@expo/vector-icons';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { SignIn } from '@/components/SignIn';
import { useAuth } from '@/hooks/useAuth';
import { useColors, fontSize, radii, spacing } from '@/theme/colors';
import { formatDate } from '@/utils/format';

export default function MeScreen() {
  const c = useColors();
  const { user, ready, signOut } = useAuth();
  return (
    <ScrollView style={{ backgroundColor: c.background }} contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
      {!ready ? (
        <ActivityIndicator color={c.brand} />
      ) : user ? (
        <View style={[styles.card, { backgroundColor: c.surface, borderColor: c.border }]}>
          <View style={styles.row}>
            <Ionicons name="person-circle-outline" size={40} color={c.brand} />
            <View style={{ flex: 1 }}>
              <Text style={[styles.email, { color: c.textPrimary }]}>{user.email}</Text>
              <Text style={[styles.meta, { color: c.textMuted }]}>Member since {formatDate(user.created_at)}</Text>
            </View>
          </View>
          <Text style={[styles.body, { color: c.textMuted }]}>
            Your saved companies and AI conversations follow this account. Custom metrics and charts are coming next.
          </Text>
          <Pressable onPress={signOut} style={[styles.btn, { borderColor: c.border }]}>
            <Text style={[styles.btnText, { color: c.negative }]}>Sign out</Text>
          </Pressable>
        </View>
      ) : (
        <SignIn intro="Your saved companies and AI conversations are kept with your account. Sign in with your email — no password." />
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: spacing.lg, gap: spacing.md },
  card: { borderWidth: StyleSheet.hairlineWidth, borderRadius: radii.lg, padding: spacing.lg, gap: spacing.md },
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  email: { fontSize: fontSize.md, fontWeight: '700' },
  meta: { fontSize: fontSize.xs, marginTop: 2 },
  body: { fontSize: fontSize.sm, lineHeight: 20 },
  btn: { alignSelf: 'flex-start', borderWidth: StyleSheet.hairlineWidth, borderRadius: radii.pill, paddingHorizontal: spacing.lg, paddingVertical: 8 },
  btnText: { fontSize: fontSize.sm, fontWeight: '700' },
});

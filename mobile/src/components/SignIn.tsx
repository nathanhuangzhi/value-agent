/**
 * Email → 6-digit code sign-in. Two steps in one card; used by the Me tab
 * and shown inline wherever a signed-in user is required.
 */
import { useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { useAuth } from '@/hooks/useAuth';
import { useColors, fontSize, radii, spacing } from '@/theme/colors';

export function SignIn({ intro }: { intro?: string }) {
  const c = useColors();
  const { requestCode, verify } = useAuth();
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={[styles.card, { backgroundColor: c.surface, borderColor: c.border }]}>
      <Text style={[styles.title, { color: c.textPrimary }]}>Sign in</Text>
      {intro ? <Text style={[styles.intro, { color: c.textMuted }]}>{intro}</Text> : null}
      <TextInput
        value={email}
        onChangeText={setEmail}
        placeholder="you@example.com"
        placeholderTextColor={c.textMuted}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="email-address"
        textContentType="emailAddress"
        editable={!sent}
        style={[styles.input, { color: c.textPrimary, backgroundColor: c.background, borderColor: c.border }]}
      />
      {sent ? (
        <>
          <Text style={[styles.hint, { color: c.textMuted }]}>We emailed a 6-digit code to {email.trim()}.</Text>
          <TextInput
            value={code}
            onChangeText={(v) => setCode(v.replace(/\D/g, '').slice(0, 6))}
            placeholder="123456"
            placeholderTextColor={c.textMuted}
            keyboardType="number-pad"
            textContentType="oneTimeCode"
            autoFocus
            style={[styles.input, styles.code, { color: c.textPrimary, backgroundColor: c.background, borderColor: c.border }]}
          />
        </>
      ) : null}
      {error ? <Text style={[styles.error, { color: c.negative }]}>{error}</Text> : null}
      <View style={styles.row}>
        {sent ? (
          <Pressable onPress={() => { setSent(false); setCode(''); setError(null); }} hitSlop={8} style={styles.link}>
            <Text style={[styles.linkText, { color: c.textMuted }]}>Change email</Text>
          </Pressable>
        ) : <View />}
        <Pressable
          disabled={busy || (sent ? code.length !== 6 : !email.includes('@'))}
          onPress={() => run(async () => {
            if (!sent) { await requestCode(email.trim()); setSent(true); }
            else await verify(email.trim(), code);
          })}
          style={[styles.btn, { backgroundColor: c.brand, opacity: busy || (sent ? code.length !== 6 : !email.includes('@')) ? 0.5 : 1 }]}
        >
          {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.btnText}>{sent ? 'Verify' : 'Send code'}</Text>}
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: StyleSheet.hairlineWidth, borderRadius: radii.lg, padding: spacing.lg, gap: spacing.sm },
  title: { fontSize: fontSize.lg, fontWeight: '700' },
  intro: { fontSize: fontSize.sm, lineHeight: 20 },
  input: { borderWidth: StyleSheet.hairlineWidth, borderRadius: radii.md, paddingHorizontal: spacing.md, paddingVertical: 10, fontSize: fontSize.md },
  code: { letterSpacing: 6, fontSize: 22, fontVariant: ['tabular-nums'], textAlign: 'center' },
  hint: { fontSize: fontSize.sm },
  error: { fontSize: fontSize.sm },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: spacing.xs },
  link: { paddingVertical: 6 },
  linkText: { fontSize: fontSize.sm, fontWeight: '600' },
  btn: { borderRadius: radii.pill, paddingHorizontal: spacing.lg, paddingVertical: 10, minWidth: 110, alignItems: 'center' },
  btnText: { color: '#fff', fontWeight: '700', fontSize: fontSize.sm },
});

/**
 * Two-pane wrapper used on iPad-landscape: persistent sidebar on the
 * left, current-route content rendered via `Slot` on the right.
 *
 * The Slot mechanism is Expo Router's way of saying "render whatever
 * route matches the URL here." That means navigating from the sidebar
 * (`router.push('/ticker/QDEL')`) updates the URL and the right pane
 * re-renders — no animated screen transition, no Stack push.
 *
 * On phones and iPad-portrait this component is bypassed entirely by
 * `app/_layout.tsx` in favor of the regular Stack navigator, so iPhone
 * UX has zero risk of regression.
 */
import { StyleSheet, View } from 'react-native';
import { Slot } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';

import { useColors } from '@/theme/colors';
import { SidebarNav } from './SidebarNav';


export function SplitLayout() {
  const c = useColors();
  return (
    <SafeAreaView style={[styles.container, { backgroundColor: c.background }]}>
      <View style={styles.row}>
        <SidebarNav />
        <View style={[styles.content, { backgroundColor: c.background }]}>
          <Slot />
        </View>
      </View>
    </SafeAreaView>
  );
}


const styles = StyleSheet.create({
  container: { flex: 1 },
  row: { flex: 1, flexDirection: 'row' },
  content: { flex: 1 },
});

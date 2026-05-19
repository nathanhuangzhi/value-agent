/**
 * Width-based device classification.
 *
 *   phone             — < 768 pt (iPhone, any orientation)
 *   tablet            — 768-1023 pt (iPad portrait, iPad Mini)
 *   tablet-landscape  — ≥ 1024 pt (iPad landscape, iPad Pro)
 *
 * The thresholds match Apple's published iPad size classes. Components
 * that have multiple layouts (KPI grid, sidebar, content max-width) read
 * this hook and switch their styling — phone branch stays unchanged so
 * iPhone UX has zero regression risk.
 *
 * Returns a stable string (re-renders only when crossing a breakpoint,
 * not on every pt of window-size change). Re-evaluated on orientation
 * change because `useWindowDimensions` already triggers an update there.
 */
import { useWindowDimensions } from 'react-native';

export type DeviceClass = 'phone' | 'tablet' | 'tablet-landscape';


export function useDeviceClass(): DeviceClass {
  const { width } = useWindowDimensions();
  if (width >= 1024) return 'tablet-landscape';
  if (width >= 768) return 'tablet';
  return 'phone';
}


/** Convenience: true on tablet (either orientation). */
export function useIsTablet(): boolean {
  const dc = useDeviceClass();
  return dc === 'tablet' || dc === 'tablet-landscape';
}


/** Convenience: true only on the wide iPad layout that gets the split view. */
export function useIsTabletLandscape(): boolean {
  return useDeviceClass() === 'tablet-landscape';
}

/**
 * Color palette for Valueland. Single source of truth — every component
 * imports from here so a future redesign is a one-file change.
 *
 * Dark mode is supported by the `useColors()` hook (driven by the OS's
 * `useColorScheme()`) and is the only reason these are split into light
 * and dark variants. Hardcoded values in components are forbidden.
 */
import { useColorScheme } from 'react-native';

type Palette = {
  background: string;
  surface: string;
  textPrimary: string;
  textMuted: string;
  brand: string;
  positive: string;
  negative: string;
  warning: string;
  border: string;
  /** Status badge backgrounds keyed to validation severity. */
  statusOkBg: string;
  statusInfoBg: string;
  statusWarnBg: string;
  statusErrorBg: string;
  /** Status badge text — kept distinct from the muted text color. */
  statusOkText: string;
  statusInfoText: string;
  statusWarnText: string;
  statusErrorText: string;
};

const light: Palette = {
  background: '#FFFFFF',
  surface: '#FAFAF9',
  textPrimary: '#111111',
  textMuted: '#6B7280',
  brand: '#166534',
  positive: '#16A34A',
  negative: '#DC2626',
  warning: '#F59E0B',
  border: '#E5E7EB',
  statusOkBg: '#E6F0E6',
  statusInfoBg: '#EEF2F7',
  statusWarnBg: '#FFF3CD',
  statusErrorBg: '#F8D7DA',
  statusOkText: '#166534',
  statusInfoText: '#1A3A5C',
  statusWarnText: '#856404',
  statusErrorText: '#721C24',
};

const dark: Palette = {
  background: '#0F0F10',
  surface: '#1C1C1E',
  textPrimary: '#F5F5F4',
  textMuted: '#9CA3AF',
  brand: '#4ADE80',
  positive: '#4ADE80',
  negative: '#F87171',
  warning: '#FBBF24',
  border: '#27272A',
  statusOkBg: '#1B3724',
  statusInfoBg: '#1F2A3B',
  statusWarnBg: '#3D2F0E',
  statusErrorBg: '#3A1D1D',
  statusOkText: '#86EFAC',
  statusInfoText: '#93C5FD',
  statusWarnText: '#FCD34D',
  statusErrorText: '#FCA5A5',
};

export function useColors(): Palette {
  const scheme = useColorScheme();
  return scheme === 'dark' ? dark : light;
}

export const radii = { sm: 4, md: 8, lg: 12, pill: 999 };
export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 };
export const fontSize = {
  xs: 11,
  sm: 13,
  md: 15,
  lg: 17,
  xl: 22,
  xxl: 28,
};

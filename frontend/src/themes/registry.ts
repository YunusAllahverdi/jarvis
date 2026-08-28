export type ThemeId = 'cosmic' | 'sakura' | 'cyberpunk';

export interface ThemeColors {
  'bg-color': string;
  'panel-bg': string;
  'panel-border': string;
  'text-primary': string;
  'text-secondary': string;
  'accent-color': string;
  'accent-hover': string;
  'danger-color': string;
  'success-color': string;
  'message-user-bg': string;
  'message-jarvis-bg': string;
}

export interface OrbConfig {
  coreColor: string;     // Primary luminous color (blue)
  glowColor: string;     // Secondary glow color (violet)
  accentColor: string;   // Tertiary accent (magenta/pink)
  waveComplexity: number; // 0.5 – 2.0
}

export interface ThemeDefinition {
  id: ThemeId;
  name: string;
  colors: ThemeColors;
  orb: OrbConfig;
  backgroundType: 'nebula' | 'sakura' | 'grid';
}

export const defaultThemes: ThemeDefinition[] = [
  {
    id: 'cosmic',
    name: 'Cosmic (Default)',
    backgroundType: 'nebula',
    orb: {
      coreColor: '#4488ff',
      glowColor: '#7c3aed',
      accentColor: '#c084fc',
      waveComplexity: 1.0,
    },
    colors: {
      'bg-color': '#020008',
      'panel-bg': 'rgba(8, 6, 18, 0.55)',
      'panel-border': 'rgba(120, 100, 255, 0.08)',
      'text-primary': '#e8e4f0',
      'text-secondary': '#8b85a0',
      'accent-color': '#7c6ef0',
      'accent-hover': '#9d8cff',
      'danger-color': '#ef4444',
      'success-color': '#10b981',
      'message-user-bg': 'rgba(100, 100, 255, 0.08)',
      'message-jarvis-bg': 'rgba(255, 255, 255, 0.02)',
    }
  },
  {
    id: 'sakura',
    name: 'Japanese Sakura',
    backgroundType: 'sakura',
    orb: {
      coreColor: '#d946a8',
      glowColor: '#a855f7',
      accentColor: '#f0abfc',
      waveComplexity: 0.85,
    },
    colors: {
      'bg-color': '#0a0008',
      'panel-bg': 'rgba(20, 8, 15, 0.55)',
      'panel-border': 'rgba(255, 140, 200, 0.08)',
      'text-primary': '#fdf2f8',
      'text-secondary': '#d4a0c0',
      'accent-color': '#d946a8',
      'accent-hover': '#f0abfc',
      'danger-color': '#ef4444',
      'success-color': '#10b981',
      'message-user-bg': 'rgba(217, 70, 168, 0.1)',
      'message-jarvis-bg': 'rgba(255, 255, 255, 0.03)',
    }
  }
];

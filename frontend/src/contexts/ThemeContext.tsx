import React, { createContext, useContext, useState, useEffect } from 'react';
import { type ThemeDefinition, defaultThemes, type ThemeId } from '../themes/registry';

interface ThemeContextType {
  currentTheme: ThemeDefinition;
  setTheme: (id: ThemeId) => void;
  availableThemes: ThemeDefinition[];
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [currentThemeId, setCurrentThemeId] = useState<ThemeId>(() => {
    return (localStorage.getItem('jarvis-theme') as ThemeId) || 'cosmic';
  });

  const currentTheme = defaultThemes.find(t => t.id === currentThemeId) || defaultThemes[0];

  const setTheme = (id: ThemeId) => {
    setCurrentThemeId(id);
    localStorage.setItem('jarvis-theme', id);
  };

  useEffect(() => {
    const root = document.documentElement;
    Object.entries(currentTheme.colors).forEach(([key, value]) => {
      root.style.setProperty(`--${key}`, value);
    });
  }, [currentTheme]);

  return (
    <ThemeContext.Provider value={{ currentTheme, setTheme, availableThemes: defaultThemes }}>
      {children}
    </ThemeContext.Provider>
  );
};

export const useTheme = () => {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
};

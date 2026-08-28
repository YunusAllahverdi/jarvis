import React, { createContext, useContext, useState, useRef, useCallback } from 'react';

export type OrbState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'error';
export type OrbPosition = 'center' | 'shifted-left';

interface UIContextType {
  orbState: OrbState;
  setOrbState: (state: OrbState) => void;
  orbIntensity: number;
  setOrbIntensity: (v: number) => void;
  activePanels: string[];
  openPanel: (panelId: string) => void;
  closePanel: (panelId: string) => void;
  orbPosition: OrbPosition;
}

const UIContext = createContext<UIContextType | undefined>(undefined);

export const UIProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [orbState, setOrbState] = useState<OrbState>('idle');
  const [orbIntensity, setOrbIntensityRaw] = useState(0);
  const [activePanels, setActivePanels] = useState<string[]>([]);
  const intensityRef = useRef(0);

  const setOrbIntensity = useCallback((v: number) => {
    intensityRef.current = Math.max(0, Math.min(1, v));
    setOrbIntensityRaw(intensityRef.current);
  }, []);

  const openPanel = useCallback((panelId: string) => {
    setActivePanels(prev => prev.includes(panelId) ? prev : [...prev, panelId]);
  }, []);

  const closePanel = useCallback((panelId: string) => {
    setActivePanels(prev => prev.filter(id => id !== panelId));
  }, []);

  const orbPosition: OrbPosition = activePanels.length > 0 ? 'shifted-left' : 'center';

  return (
    <UIContext.Provider value={{
      orbState, setOrbState,
      orbIntensity, setOrbIntensity,
      activePanels, openPanel, closePanel,
      orbPosition,
    }}>
      {children}
    </UIContext.Provider>
  );
};

export const useUI = () => {
  const ctx = useContext(UIContext);
  if (!ctx) throw new Error('useUI must be used within a UIProvider');
  return ctx;
};

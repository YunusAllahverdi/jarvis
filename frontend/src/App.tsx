import { useEffect } from 'react';
import { ThemeProvider } from './contexts/ThemeContext';
import { UIProvider, useUI } from './contexts/UIContext';
import { AmbientBackground } from './components/Core/AmbientBackground';
import { LayoutOrchestrator } from './components/Core/LayoutOrchestrator';
import { FloatingChat } from './components/Chat/FloatingChat';
import { SystemPanel } from './components/Panels/SystemPanel';
import { apiClient } from './api/client';

const InnerApp = () => {
  const { activePanels, closePanel } = useUI();
  
  useEffect(() => {
    // Optionally pre-warm or check backend status here
    apiClient.getHealth().catch(() => console.warn('Backend unavailable on startup.'));
  }, []);

  return (
    <>
      <AmbientBackground />
      <LayoutOrchestrator
        chat={<FloatingChat />}
        panels={
          <>
            {activePanels.includes('system') && (
              <SystemPanel onClose={() => closePanel('system')} />
            )}
            {/* Future panels go here */}
          </>
        }
      />
    </>
  );
};

function App() {
  return (
    <ThemeProvider>
      <UIProvider>
        <InnerApp />
      </UIProvider>
    </ThemeProvider>
  );
}

export default App;

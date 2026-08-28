import { motion, AnimatePresence } from 'framer-motion';
import { useUI } from '../../contexts/UIContext';
import { OrbContainer } from './Orb';

interface LayoutProps {
  chat: React.ReactNode;
  panels: React.ReactNode;
}

export const LayoutOrchestrator: React.FC<LayoutProps> = ({ chat, panels }) => {
  const { orbPosition, activePanels } = useUI();

  return (
    <div style={{ position: 'fixed', inset: 0, overflow: 'hidden', zIndex: 1 }}>

      {/* ── Living Orb ── */}
      <motion.div
        initial={false}
        animate={{
          left: orbPosition === 'center' ? '50%' : '32%',
          top:  '42%',
          scale: orbPosition === 'center' ? 1 : 0.78,
          x: '-50%',
          y: '-50%',
        }}
        transition={{ type: 'spring', stiffness: 40, damping: 28 }}
        style={{
          position: 'absolute',
          /*
           * 28vw centered — NOT 50vw.
           * Leaves substantial negative space.
           * min/max keep it sane across viewports.
           */
          width:  'min(28vw, 380px)',
          height: 'min(28vw, 380px)',
          zIndex: 10,
          pointerEvents: 'none',
        }}
      >
        <OrbContainer />
      </motion.div>

      {/* ── Panel area (right side) ── */}
      <AnimatePresence>
        {activePanels.length > 0 && (
          <motion.div
            initial={{ opacity: 0, x: 80, scale: 0.96 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            exit={{ opacity: 0, x: 80, scale: 0.96 }}
            transition={{ type: 'spring', stiffness: 55, damping: 22 }}
            style={{
              position: 'absolute',
              right: '2.5rem', top: '3rem', bottom: '3rem',
              width: '420px',
              zIndex: 30,
              display: 'flex', flexDirection: 'column', gap: '16px',
              pointerEvents: 'auto',
              overflowY: 'auto',
            }}
          >
            {panels}
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Floating chat — bottom center, follows orb horizontal ── */}
      <motion.div
        animate={{
          left: orbPosition === 'center' ? '50%' : '32%',
          x: '-50%',
        }}
        transition={{ type: 'spring', stiffness: 40, damping: 28 }}
        style={{
          position: 'absolute',
          bottom: '4vh',
          width: '92%',
          maxWidth: '620px',
          zIndex: 20,
          pointerEvents: 'auto',
        }}
      >
        {chat}
      </motion.div>
    </div>
  );
};

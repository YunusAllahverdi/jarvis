import { X } from 'lucide-react';

interface PanelContainerProps {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}

export const PanelContainer: React.FC<PanelContainerProps> = ({ title, onClose, children }) => {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      borderRadius: '16px',
      background: 'rgba(8, 6, 18, 0.55)',
      backdropFilter: 'blur(28px)',
      WebkitBackdropFilter: 'blur(28px)',
      border: '1px solid rgba(120, 100, 255, 0.08)',
      boxShadow: '0 12px 50px rgba(0, 0, 0, 0.35)',
      overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        padding: '14px 18px',
        borderBottom: '1px solid rgba(120, 100, 255, 0.06)',
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      }}>
        <h3 style={{
          margin: 0, fontSize: '0.9rem', fontWeight: 500,
          color: 'var(--text-primary)',
          letterSpacing: '0.03em',
        }}>{title}</h3>
        <button
          onClick={onClose}
          style={{
            width: '28px', height: '28px',
            borderRadius: '50%',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'transparent',
            border: 'none', cursor: 'pointer',
            color: 'var(--text-secondary)',
            transition: 'all 0.2s ease',
          }}
          onMouseEnter={e => {
            (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.06)';
          }}
          onMouseLeave={e => {
            (e.currentTarget as HTMLElement).style.background = 'transparent';
          }}
        >
          <X size={15} />
        </button>
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '14px 18px' }}>
        {children}
      </div>
    </div>
  );
};

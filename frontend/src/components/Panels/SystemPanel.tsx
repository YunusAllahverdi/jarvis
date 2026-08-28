import { PanelContainer } from './PanelContainer';
import { Cpu, HardDrive, Network } from 'lucide-react';

interface SystemPanelProps { onClose: () => void; }

const StatRow = ({ icon: Icon, label, value, valueColor }: {
  icon: React.ElementType; label: string; value: string; valueColor: string;
}) => (
  <div style={{
    padding: '14px',
    background: 'rgba(255,255,255,0.02)',
    borderRadius: '10px',
    border: '1px solid rgba(120, 100, 255, 0.05)',
  }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px' }}>
      <Icon size={17} color="var(--accent-color)" />
      <span style={{ fontWeight: 500, fontSize: '0.88rem' }}>{label}</span>
    </div>
    <div style={{
      display: 'flex', justifyContent: 'space-between',
      fontSize: '0.8rem', color: 'var(--text-secondary)',
    }}>
      <span>Status</span>
      <span style={{ color: valueColor }}>{value}</span>
    </div>
  </div>
);

export const SystemPanel: React.FC<SystemPanelProps> = ({ onClose }) => (
  <PanelContainer title="System Diagnostics" onClose={onClose}>
    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
      <StatRow icon={Cpu}       label="Core Processing"  value="Nominal" valueColor="var(--success-color)" />
      <StatRow icon={HardDrive} label="Memory Vault"      value="Optimized" valueColor="var(--success-color)" />
      <StatRow icon={Network}   label="External Links"    value="Disconnected" valueColor="var(--danger-color)" />
    </div>
  </PanelContainer>
);

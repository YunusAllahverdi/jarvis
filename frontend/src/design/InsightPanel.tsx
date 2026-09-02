import { useCallback, useEffect, useState } from 'react';
import {
  apiClient,
  type ExperienceView,
  type MemoryRecordView,
  type SystemStatus,
  type UserProfile,
} from '../api/client';

/**
 * Gezinme başlıklarının açtığı salt-okunur ekranlar.
 *
 * Bu paneller yeni bir yetenek eklemez; depolarda ZATEN duran veriyi
 * gösterirler. Daha önce bu başlıklar hiçbir şey açmıyor, yanlarındaki
 * kutular ise tasarımdan gelen sabit örneklerle doluydu — yani arayüz,
 * olmayan bir şeyi varmış gibi gösteriyordu.
 *
 * Boş durum GİZLENMEZ: hiç kayıt yoksa bunu açıkça söyleriz. "Henüz bir şey
 * yok" demek, sahte üç satır göstermekten dürüsttür.
 */

const PANEL: React.CSSProperties = {
  borderRadius: 15,
  background: 'rgba(14,13,32,0.92)',
  border: '1px solid rgba(140,150,255,0.18)',
  backdropFilter: 'blur(20px)',
};

const MONO = "'JetBrains Mono', ui-monospace, monospace";

const FIELD: React.CSSProperties = {
  flex: 1,
  height: 38,
  padding: '0 14px',
  borderRadius: 10,
  background: 'rgba(140,150,255,0.06)',
  border: '1px solid rgba(140,150,255,0.16)',
  color: '#dfe2ff',
  fontSize: 13,
  fontFamily: 'inherit',
  outline: 'none',
};

export type InsightSection =
  | 'Bellek'
  | 'Deneyimler'
  | 'Öğrendiklerim'
  | 'Benim Modelim'
  | 'Sistem';

const SUBTITLE: Record<InsightSection, string> = {
  Bellek: 'Jarvis ne biliyor — kalıcı bellek kayıtları',
  Deneyimler: 'Ne oldu — son etkileşimler',
  Öğrendiklerim: 'Zamanla çıkarılan kalıcı örüntüler',
  'Benim Modelim': 'Kullanıcı modelinin özeti',
  Sistem: 'Sunucunun ölçülen kaynak kullanımı',
};

interface Props {
  section: InsightSection;
  onClose: () => void;
}

export const InsightPanel = ({ section, onClose }: Props) => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');

  const [records, setRecords] = useState<MemoryRecordView[]>([]);
  const [experiences, setExperiences] = useState<ExperienceView[]>([]);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [system, setSystem] = useState<SystemStatus | null>(null);

  const load = useCallback(
    async (searchTerm = '') => {
      setLoading(true);
      setError(null);
      try {
        if (section === 'Bellek') {
          setRecords((await apiClient.getMemoryRecords(searchTerm)).records);
        } else if (section === 'Deneyimler') {
          setExperiences((await apiClient.getExperiences()).experiences);
        } else if (section === 'Sistem') {
          setSystem(await apiClient.getSystemStatus());
        } else {
          setProfile(await apiClient.getUserProfile());
        }
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : 'Veri okunamadı.');
      } finally {
        setLoading(false);
      }
    },
    [section],
  );

  useEffect(() => { void load(); }, [load]);

  return (
    <div
      onClick={onClose}
      style={{
        position: 'absolute', inset: 0, zIndex: 20,
        background: 'rgba(4,3,12,0.55)', display: 'grid', placeItems: 'center',
      }}
    >
      <div
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-label={section}
        style={{
          ...PANEL, width: 660, maxHeight: 720, padding: 22,
          display: 'flex', flexDirection: 'column', gap: 16,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 500, color: '#dfe2ff' }}>{section}</div>
            <div style={{ fontSize: 11, color: '#8b96c8', marginTop: 3 }}>{SUBTITLE[section]}</div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={() => void load(query)}
              aria-label="Yenile"
              style={{
                height: 28, padding: '0 10px', borderRadius: 8, cursor: 'pointer',
                background: 'transparent', border: '1px solid rgba(140,150,255,0.16)',
                color: '#aab4e8', fontSize: 11.5, fontFamily: 'inherit',
              }}
            >
              Yenile
            </button>
            <button
              onClick={onClose}
              aria-label="Kapat"
              style={{
                width: 28, height: 28, borderRadius: 8, cursor: 'pointer',
                background: 'transparent', border: '1px solid rgba(140,150,255,0.16)',
                color: '#aab4e8', fontSize: 14, lineHeight: 1,
              }}
            >
              ×
            </button>
          </div>
        </div>

        {section === 'Bellek' && (
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') { event.preventDefault(); void load(query); }
              }}
              placeholder="Bellekte ara"
              aria-label="Bellekte ara"
              style={FIELD}
            />
          </div>
        )}

        {loading && <Muted>Yükleniyor...</Muted>}
        {error && (
          <div role="status" style={{ fontSize: 12.5, color: '#f1798f', lineHeight: 1.55 }}>
            {error}
          </div>
        )}

        {!loading && !error && (
          <div style={{ overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 12, paddingRight: 4 }}>
            {section === 'Bellek' && <MemoryList records={records} searched={!!query.trim()} />}
            {section === 'Deneyimler' && <ExperienceList experiences={experiences} />}
            {section === 'Öğrendiklerim' && <TraitList profile={profile} />}
            {section === 'Benim Modelim' && <ProfileSummary profile={profile} />}
            {section === 'Sistem' && <SystemView status={system} />}
          </div>
        )}
      </div>
    </div>
  );
};

/* ── ortak parçalar ──────────────────────────────────────── */

const Muted = ({ children }: { children: React.ReactNode }) => (
  <div style={{ fontSize: 12.5, color: '#8b96c8', lineHeight: 1.6 }}>{children}</div>
);

const Row = ({ label, value }: { label: string; value: string }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, fontFamily: MONO }}>
    <span style={{ color: '#939ec9' }}>{label}</span>
    <span style={{ color: '#d7dcff' }}>{value}</span>
  </div>
);

const Card = ({ children }: { children: React.ReactNode }) => (
  <div style={{
    padding: 13, borderRadius: 11,
    background: 'rgba(140,150,255,0.05)', border: '1px solid rgba(140,150,255,0.12)',
    display: 'flex', flexDirection: 'column', gap: 7,
  }}>
    {children}
  </div>
);

const formatDate = (iso: string) => {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString('tr-TR');
};

const formatBytes = (bytes: number) => `${(bytes / 1024 ** 3).toFixed(1)} GB`;

/* ── bölümler ────────────────────────────────────────────── */

const MemoryList = ({ records, searched }: { records: MemoryRecordView[]; searched: boolean }) => {
  if (records.length === 0) {
    return (
      <Muted>
        {searched
          ? 'Bu aramayla eşleşen kayıt yok.'
          : 'Henüz bellek kaydı yok. Jarvis konuştukça buraya kayıtlar düşecek.'}
      </Muted>
    );
  }
  return (
    <>
      {records.map((record) => (
        <Card key={record.id}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10.5, fontFamily: MONO, color: '#8b96c8' }}>
            <span>{record.memory_type}</span>
            <span>{formatDate(record.valid_at)}</span>
          </div>
          <div style={{ fontSize: 12.5, color: '#d3d8ff', lineHeight: 1.55 }}>{record.content}</div>
        </Card>
      ))}
    </>
  );
};

const ExperienceList = ({ experiences }: { experiences: ExperienceView[] }) => {
  if (experiences.length === 0) {
    return <Muted>Henüz kaydedilmiş bir deneyim yok.</Muted>;
  }
  return (
    <>
      {experiences.map((item) => (
        <Card key={item.id}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10.5, fontFamily: MONO, color: '#8b96c8' }}>
            <span>{formatDate(item.occurred_at)}</span>
            <span style={{ color: item.outcome === 'success' ? '#8fd9b6' : '#f0c675' }}>
              {item.outcome}
            </span>
          </div>
          <div style={{ fontSize: 12.5, color: '#d3d8ff', lineHeight: 1.55 }}>{item.user_message}</div>
          {item.assistant_response && (
            <div style={{ fontSize: 12, color: '#9aa4cc', lineHeight: 1.55 }}>
              {item.assistant_response}
            </div>
          )}
          {item.tool_calls.length > 0 && (
            <div style={{ fontSize: 10.5, fontFamily: MONO, color: '#7a85b5' }}>
              {item.tool_calls.join(', ')}
            </div>
          )}
        </Card>
      ))}
    </>
  );
};

const TraitList = ({ profile }: { profile: UserProfile | null }) => {
  if (!profile || profile.traits.length === 0) {
    return (
      <Muted>
        Henüz çıkarılmış bir örüntü yok. Bunlar yeterli etkileşim biriktikçe
        kendiliğinden oluşur.
      </Muted>
    );
  }
  return (
    <>
      {profile.traits.map((trait) => (
        <Card key={trait.id}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10.5, fontFamily: MONO, color: '#8b96c8' }}>
            <span>{trait.trait_type} · {trait.key}</span>
            <span>güven {(trait.confidence * 100).toFixed(0)}%</span>
          </div>
          <div style={{ fontSize: 12.5, color: '#d3d8ff', lineHeight: 1.55 }}>{trait.value}</div>
          <div style={{ fontSize: 10.5, fontFamily: MONO, color: '#7a85b5' }}>
            {trait.evidence_count} gözlem · {formatDate(trait.last_observed_at)}
          </div>
        </Card>
      ))}
    </>
  );
};

const ProfileSummary = ({ profile }: { profile: UserProfile | null }) => {
  if (!profile) return <Muted>Kullanıcı modeli okunamadı.</Muted>;

  const byType = Object.entries(profile.traits_by_type).filter(([, count]) => count > 0);
  const interaction = Object.entries(profile.interaction);

  return (
    <>
      <Card>
        <Row label="Toplam örüntü" value={String(profile.trait_count)} />
        <Row label="Üretildiği an" value={formatDate(profile.generated_at)} />
      </Card>

      {byType.length > 0 && (
        <Card>
          <div style={{ fontSize: 11, color: '#8b96c8', marginBottom: 2 }}>Türe göre</div>
          {byType.map(([type, count]) => (
            <Row key={type} label={type} value={String(count)} />
          ))}
        </Card>
      )}

      {interaction.length > 0 && (
        <Card>
          <div style={{ fontSize: 11, color: '#8b96c8', marginBottom: 2 }}>Etkileşim</div>
          {interaction.map(([key, value]) => (
            <Row key={key} label={key} value={value === null ? '—' : String(value)} />
          ))}
        </Card>
      )}

      {profile.trait_count === 0 && (
        <Muted>Henüz bir örüntü çıkarılmadı; model boş görünüyor.</Muted>
      )}
    </>
  );
};

const SystemView = ({ status }: { status: SystemStatus | null }) => {
  if (!status) return <Muted>Sistem durumu okunamadı.</Muted>;
  return (
    <>
      {/* Bu uyarı bir süsleme değil: bulutta çalışan bir örnek container'ı
          ölçer, kullanıcının bilgisayarını değil. */}
      {!status.is_local && (
        <div style={{ fontSize: 11.5, color: '#f0c675', lineHeight: 1.55 }}>
          Sunucu yerel adres dışına bağlı. Buradaki değerler sunucunun kaynaklarıdır,
          sizin bilgisayarınızın değil.
        </div>
      )}
      <Card>
        <Row label="CPU" value={`${status.cpu_percent.toFixed(0)}%`} />
        <Row label="Bellek" value={`${status.memory_percent.toFixed(0)}%`} />
        <Row
          label="Bellek boş"
          value={`${formatBytes(status.memory_available_bytes)} / ${formatBytes(status.memory_total_bytes)}`}
        />
      </Card>
      <Card>
        <Row label="Disk" value={`${status.disk_percent.toFixed(0)}%`} />
        <Row
          label="Disk boş"
          value={`${formatBytes(status.disk_free_bytes)} / ${formatBytes(status.disk_total_bytes)}`}
        />
      </Card>
    </>
  );
};

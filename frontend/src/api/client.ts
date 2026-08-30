// Backend ile tek temas noktası. Yollar göreli: geliştirmede Vite
// /api'yi uvicorn'a proxy'liyor, dağıtımda ikisi aynı origin'de olacak.

const API_BASE = '/api';

export interface ChatMessage {
  message: string;
  session_id?: string | null;
}

export interface ChatResponse {
  response: string;
  session_id: string;
}

export interface HealthResponse {
  status: string;
  version?: string;
}

/**
 * Başarısız bir yanıttan okunabilir bir mesaj çıkarır.
 *
 * Gövde her zaman JSON değildir: backend çalışmıyorken proxy düz metin
 * 502 döndürür ve response.json() orada patlar. Bu yüzden önce metin
 * olarak okunup JSON ayrıştırması denenir.
 */
async function errorMessage(response: Response): Promise<string> {
  let body = '';
  try {
    body = await response.text();
  } catch {
    // Gövde okunamadı; aşağıdaki durum koduna düşülür.
  }

  if (body) {
    try {
      const parsed = JSON.parse(body) as { detail?: { message?: string } | string };
      const detail = parsed.detail;
      if (typeof detail === 'string') return detail;
      if (detail?.message) return detail.message;
    } catch {
      // JSON değil — ham gövde kullanıcıya gösterilmez, sunucu hatasıdır.
    }
  }

  if (response.status === 502 || response.status === 503 || response.status === 504) {
    return 'Sunucuya ulaşılamıyor. Backend çalışıyor mu?';
  }
  return `Sunucu ${response.status} döndü.`;
}


export type LLMProviderKind = 'ollama' | 'openai_compatible';

export interface LLMConfig {
  kind: LLMProviderKind;
  base_url: string;
  model: string | null;
  timeout_seconds: number;
  /** Anahtarın kendisi hiç gelmez; yalnızca tanımlı olup olmadığı. */
  has_api_key: boolean;
}

export interface LLMConfigUpdate {
  kind: LLMProviderKind;
  base_url: string;
  model: string | null;
  timeout_seconds?: number;
  /** Boş bırakılırsa sunucudaki mevcut anahtar korunur. */
  api_key?: string;
  clear_api_key?: boolean;
}

export const apiClient = {
  /** Bir mesajı Jarvis'e gönderir ve cevabı döndürür. */
  async chat(message: string, sessionId?: string | null): Promise<ChatResponse> {
    const payload: ChatMessage = { message, session_id: sessionId || null };

    let response: Response;
    try {
      response = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    } catch {
      // Ağ seviyesinde hata: sunucu hiç yanıt vermedi.
      throw new Error('Sunucuya ulaşılamıyor. Backend çalışıyor mu?');
    }

    if (!response.ok) throw new Error(await errorMessage(response));
    return response.json() as Promise<ChatResponse>;
  },

  /** Backend'in ayakta olup olmadığını kontrol eder. */
  async getHealth(): Promise<HealthResponse> {
    const response = await fetch(`${API_BASE}/v1/health`);
    if (!response.ok) throw new Error(await errorMessage(response));
    return response.json() as Promise<HealthResponse>;
  },

  /** Geçerli sağlayıcı yapılandırmasını okur (anahtar hariç). */
  async getLlmConfig(): Promise<LLMConfig> {
    const response = await fetch(`${API_BASE}/admin/llm`);
    if (!response.ok) throw new Error(await errorMessage(response));
    return response.json() as Promise<LLMConfig>;
  },

  /** Sağlayıcıyı değiştirir; sunucuda hemen devreye girer. */
  async updateLlmConfig(update: LLMConfigUpdate): Promise<LLMConfig> {
    const response = await fetch(`${API_BASE}/admin/llm`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(update),
    });
    if (!response.ok) throw new Error(await errorMessage(response));
    return response.json() as Promise<LLMConfig>;
  },
};

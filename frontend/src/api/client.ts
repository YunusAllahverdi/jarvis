// API Client Layer

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

export const apiClient = {
  /**
   * Send a chat message to the Jarvis backend
   */
  async chat(message: string, sessionId?: string | null): Promise<ChatResponse> {
    const payload: ChatMessage = { message, session_id: sessionId || null };
    
    const response = await fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail?.message || 'Chat API request failed');
    }

    return response.json();
  },

  /**
   * Check the health status of the backend
   */
  async getHealth(): Promise<HealthResponse> {
    const response = await fetch(`${API_BASE}/v1/health`);
    
    if (!response.ok) {
      throw new Error('Health check failed');
    }
    
    return response.json();
  }
};

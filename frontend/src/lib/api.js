// Backend ile TEK temas noktası. Bileşenler hiçbir zaman URL kurmaz.
//
// Bu dosya Emergent şablonundaki sürümün yerine geçti. Şablon, kendi
// MongoDB'li tek dosyalık sunucusuna konuşuyordu; burada aynı arayüz
// GERÇEK Jarvis backend'ine bağlanıyor.
//
// İki tür yöntem var ve ayrımı görünür tutmak bilinçli:
//
//   * Gerçek uca bağlananlar — çağrı yapar, gerekiyorsa yanıtı panelin
//     beklediği şekle çevirir.
//   * notConnected(...) dönenler — backend'de karşılığı OLMAYAN
//     yetenekler. Sahte veri üretmek yerine tanınabilir bir hatayla
//     reddedilir; panel bunu "bağlı değil" olarak gösterir.
//
// Uydurma üçüncü bir seçenek yok: bir panelin dolu görünüp aslında boş
// olması, çalışan panellere olan güveni de götürürdü.
import axios from "axios";

/* ── adres ────────────────────────────────────────────────────
 *
 * Varsayılan BOŞ dize, yani aynı origin. Geliştirmede craco /api'yi
 * backend'e proxy'ler, dağıtımda backend derlenmiş kabuğu kendisi sunar.
 * Her iki durumda da tarayıcı için tek bir origin vardır.
 *
 * REACT_APP_BACKEND_URL yalnızca backend BAŞKA bir makinedeyse gerekir
 * (ör. tabletten PC'ye bağlanmak).
 */
const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "";
export const API_BASE = BACKEND_URL + "/api";

/* ── kimlik ───────────────────────────────────────────────────
 *
 * Sunucu ağa açıldığında (tabletten kullanmak için) anahtar zorunlu olur
 * ve her isteğe X-Jarvis-Token olarak eklenir.
 *
 * NEDEN localStorage: bu, kullanıcının KENDİ sunucusuna girmek için
 * kullandığı erişim anahtarıdır — tarayıcının bir oturumu hatırlayabildiği
 * tek yer burasıdır. Sağlayıcı anahtarları (Anthropic, Google) ise buraya
 * HİÇ GELMEZ; onlar sunucuda durur ve API yalnızca "tanımlı mı" der.
 * Karıştırılmamalı: biri kapının anahtarı, diğeri kasanın.
 */
const TOKEN_KEY = "jarvis.api.token";

export function getToken() {
  try {
    return window.localStorage.getItem(TOKEN_KEY) || "";
  } catch {
    // Gizli sekme ya da site verisi engelli: erişimin kendisi patlar.
    return "";
  }
}

export function setToken(value) {
  try {
    const clean = (value || "").trim();
    if (clean) window.localStorage.setItem(TOKEN_KEY, clean);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Yazılamaması hata değil; anahtar yalnızca kalıcı olmaz.
  }
}

const http = axios.create({
  baseURL: API_BASE,
  headers: { "Content-Type": "application/json" },
  timeout: 120000,
});

http.interceptors.request.use((cfg) => {
  const token = getToken();
  if (token) cfg.headers["X-Jarvis-Token"] = token;
  return cfg;
});

http.interceptors.response.use(
  (r) => r,
  (err) => {
    const detail = err?.response?.data?.detail;
    const msg = typeof detail === "string" ? detail : detail?.message || err.message;
    err.jarvis = {
      code: detail?.code,
      message: msg,
      status: err?.response?.status,
      // 401/403 ayrı işaretlenir: "anahtar gerekiyor" ile "sunucu çökmüş"
      // aynı kutuda gösterilseydi kullanıcı yanlış şeyi düzeltmeye çalışırdı.
      needsAuth: err?.response?.status === 401 || err?.response?.status === 403,
    };
    return Promise.reject(err);
  }
);

/* ── bağlı olmayan yetenekler ─────────────────────────────────
 *
 * Emergent arayüzü, kendi sunucusunda var olan ama bizim backend'imizde
 * BULUNMAYAN birkaç yetenek için ekran taşıyor. Bunlara sahte veri
 * üretmek yerine tanınabilir bir kodla reddediyoruz; _shell.jsx bu kodu
 * görünce kırmızı "Hata" yerine nötr bir "bağlı değil" kutusu çiziyor.
 */
export const NOT_CONNECTED = "not_connected";

function notConnected(what, why) {
  const err = new Error(what);
  err.jarvis = { code: NOT_CONNECTED, message: what, why };
  return Promise.reject(err);
}

/* ── şekil çevirileri ─────────────────────────────────────────
 *
 * Emergent panelleri kendi sunucusunun alan adlarını bekliyor. Panelleri
 * tek tek düzenlemek yerine çeviri BURADA yapılıyor: alan adı değişirse
 * düzeltilecek tek bir yer olur ve paneller backend'in iç şemasına
 * bağlanmamış kalır.
 */
const toNote = (n) => ({
  id: n.id,
  title: n.title,
  content: n.content,
  // Ajanın yazdığı notu kullanıcı kendi yazdığından ayırabilmeli.
  author: n.created_by === "agent" ? "agent" : "user",
  tags: [],
  updated_at: n.updated_at,
  created_at: n.created_at,
});

const toApproval = (a) => ({
  id: a.approval_id,
  tool: a.tool_name,
  arguments: a.arguments,
  permission: a.permission,
  reason: a.reason,
  created_at: a.created_at,
  expires_at: a.expires_at,
});

const toCheckpoint = (c) => ({
  id: c.checkpoint_id,
  path: c.path,
  label: c.reason || c.path,
  created_at: c.created_at,
  // Backend "geri alınabilir mi"yi söyler; panel "geri alındı mı" bekliyordu.
  // Geri alınamayan bir noktada düğme göstermek, basılınca hata veren bir
  // düğme göstermek olurdu.
  restored: !c.restorable,
  existed: c.existed,
});

const toMemory = (m) => ({
  id: m.id,
  kind: m.memory_type,
  text: m.content,
  ts: m.valid_at,
  importance: m.importance,
});

export const api = {
  /* ── sistem ── */

  health: () => http.get("/v1/health").then((r) => r.data),

  systemStatus: () => http.get("/system/status").then((r) => r.data),

  agentTools: () => http.get("/agent/tools").then((r) => r.data),

  /* ── sohbet ── */

  chat: (message, session_id) =>
    http.post("/chat", { message, session_id: session_id || null }).then((r) => r.data),

  // Oturum geçmişi backend'de konuşma deposunda tutuluyor ama listeleyen
  // bir uç YOK. Uydurmak yerine bağlı değil deniyor.
  listSessions: () =>
    notConnected(
      "Oturum listesi bağlı değil.",
      "Konuşmalar sunucuda saklanıyor ama onları listeleyen bir uç yok."
    ),
  sessionMessages: () => notConnected("Oturum geçmişi bağlı değil."),
  deleteSession: () => notConnected("Oturum silme bağlı değil."),

  /* ── notlar ── */

  listNotes: () =>
    http.get("/notes").then((r) => ({ notes: (r.data.notes || []).map(toNote) })),

  createNote: (n) =>
    http
      .post("/notes", { content: n.content || "", title: n.title || "" })
      .then((r) => toNote(r.data)),

  updateNote: (id, n) =>
    http
      .put("/notes/" + id, { content: n.content || "", title: n.title || "" })
      .then((r) => toNote(r.data)),

  deleteNote: (id) => http.delete("/notes/" + id).then(() => ({ ok: true })),

  /* ── onaylar ── */

  listApprovals: () =>
    http.get("/approvals").then((r) => ({ approvals: (r.data.pending || []).map(toApproval) })),

  // Onay isteğini ARAYÜZ oluşturamaz: onay, ajanın bir aracı çağırmak
  // istemesiyle doğar. Frontend'den yaratılabilseydi, onay mekanizması
  // kendi kendini onaylayan bir formaliteye dönerdi.
  createApproval: () =>
    notConnected(
      "Onay isteği arayüzden oluşturulamaz.",
      "Onay, ajanın bir araç çağırmak istemesiyle doğar."
    ),

  decideApproval: (id, decision) =>
    http.post("/approvals/" + id, { decision }).then((r) => r.data),

  /* ── geri alma noktaları ── */

  listCheckpoints: () =>
    http
      .get("/checkpoints")
      .then((r) => ({ checkpoints: (r.data.checkpoints || []).map(toCheckpoint) })),

  createCheckpoint: () =>
    notConnected(
      "Geri alma noktası arayüzden oluşturulamaz.",
      "Nokta, bir dosya değiştirilmeden hemen önce otomatik açılır."
    ),

  restoreCheckpoint: (id) =>
    http.post("/checkpoints/" + id + "/restore").then((r) => r.data),

  /* ── sağlayıcı ── */

  getLLM: () => http.get("/admin/llm").then((r) => r.data),
  putLLM: (cfg) => http.put("/admin/llm", cfg).then((r) => r.data),

  /* ── council ── */

  getCouncil: () => http.get("/admin/council").then((r) => r.data),
  upsertMember: (id, m) => http.put("/admin/council/members/" + id, m).then((r) => r.data),
  deleteMember: (id) => http.delete("/admin/council/members/" + id).then((r) => r.data),

  /* ── ajan panel kanalı ── */

  pollUIActions: (session_id) =>
    http.get("/ui/actions", { params: session_id ? { session_id } : {} }).then((r) => r.data),

  // Kanal tek yönlüdür: ajan panel açmak İSTER, arayüz okur ve tüketir.
  // Ters yön olsaydı arayüz kendi kendine "ajan şunu istedi" diyebilirdi.
  postUIAction: () => notConnected("Panel kanalı tek yönlüdür."),

  /* ── kodlama döngüsü ── */

  codingRun: (message, session_id) =>
    http.post("/coding/run", { message, session_id: session_id || null }).then((r) => r.data),

  /* ── bellek ── */

  listMemory: (kind, q) =>
    http
      .get("/memory/records", { params: { limit: 50, ...(q ? { query: q } : {}) } })
      .then((r) => {
        const items = (r.data.records || []).map(toMemory);
        // Tür süzmesi istemcide: uç memory_type parametresi almıyor ve
        // almayan bir uca göndermek sessizce yok sayılan bir istek olurdu.
        return { items: kind ? items.filter((m) => m.kind === kind) : items };
      }),

  // Belleğe elle yazma yok ve olmaması bilinçli: bellek, konuşmadan
  // ÇIKARILAN bilgidir. Elle eklenen bir kayıt, "bunu nereden biliyorsun?"
  // sorusunun cevabını bozardı. Kalıcı bir şey yazmak isteyen not yazar.
  addMemory: () =>
    notConnected(
      "Belleğe elle kayıt eklenemez.",
      "Bellek konuşmadan çıkarılır. Kalıcı bir şey için Notlar'ı kullanın."
    ),

  /* ── deneyimler ve kullanıcı modeli ── */

  experiences: (limit) =>
    http.get("/experiences", { params: { limit: limit || 20 } }).then((r) => r.data),

  userProfile: () => http.get("/user/profile").then((r) => r.data),

  /*
   * Panel komut çubuğu.
   *
   * Emergent'te bu /panels/command adında ayrı bir uçtu. Bizde öyle bir
   * uç YOK — ama aynı şeyi yapan gerçek bir yol var: mesajı normal sohbete
   * göndermek. Ajan aracı kendi seçer, WRITE ise onay akışı devreye girer.
   *
   * Yani "Jarvis, yarınki toplantı için not yaz" cümlesi burada da,
   * sohbette de AYNI yoldan geçiyor. Ayrı bir uç açmak, izin ve onay
   * kurallarını ikinci bir yerde tekrar etmek demekti; biri güncellenip
   * diğeri unutulduğunda panel, sohbetin izin vermediği bir şeyi
   * yapabilir hâle gelirdi.
   */
  panelCommand: (panel, message) =>
    http.post("/chat", { message, session_id: null }).then((r) => ({
      reply: r.data.response,
      session_id: r.data.session_id,
      actions: [],
    })),

  /* ── backend'de karşılığı olmayanlar ── */

  listEvents: () =>
    notConnected("Takvim bağlı değil.", "Takvim için bir uç ve bir depo gerekiyor."),
  createEvent: () => notConnected("Takvim bağlı değil."),
  deleteEvent: () => notConnected("Takvim bağlı değil."),

  listReminders: () =>
    notConnected(
      "Hatırlatıcılar bağlı değil.",
      "Zamanlanmış iş için sunucuda bir zamanlayıcı gerekiyor. Şimdilik Notlar'daki kontrol listesi maddeleri bu işi görüyor."
    ),
  createReminder: () => notConnected("Hatırlatıcılar bağlı değil."),
  patchReminder: () => notConnected("Hatırlatıcılar bağlı değil."),
  deleteReminder: () => notConnected("Hatırlatıcılar bağlı değil."),

  weather: () =>
    notConnected("Hava durumu bağlı değil.", "Bir hava durumu sağlayıcısı ve aracı gerekiyor."),

  translate: () =>
    notConnected(
      "Ayrı çeviri ucu yok.",
      "Çeviri için sohbete yazmanız yeterli — model zaten çeviriyor."
    ),
};

/*
 * Akış (streaming).
 *
 * Backend'de /chat/stream YOK; /api/chat cevabı tek parça döner. Bu
 * yüzden akış SAHTE üretilmiyor — sahte bir daktilo efekti, cevabın
 * parça parça geldiği izlenimi verir ve kullanıcı ilk kelimeyi gördüğünde
 * modelin çalışmaya başladığını sanırdı; oysa cevap çoktan bitmiştir.
 *
 * Bunun yerine tek çağrı yapılıp sonuç bir kerede veriliyor. Arayüz
 * bekleme süresini küre ve "düşünüyor" durumuyla gösteriyor.
 */
export async function streamChat({ message, session_id, onSession, onDelta, onDone, onError }) {
  try {
    const data = await api.chat(message, session_id);
    onSession?.(data.session_id);
    onDelta?.(data.response);
    onDone?.({ session_id: data.session_id });
  } catch (e) {
    onError?.(e);
  }
}

export const STREAMING_SUPPORTED = false;

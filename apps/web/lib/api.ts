// API client for the CreatorPulse FastAPI service.
// Base URL is inlined at build time from NEXT_PUBLIC_API_URL — it MUST be set
// in the Vercel project (Production + Preview) before the build, or it bakes
// as localhost and the deployed site can't reach the API.
const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface Stats {
  creators: number;
  niches: number;
  archetypes: number;
}

export interface CreatorSummary {
  channel_id: string;
  title: string;
  thumbnail_url: string;
  niche: string;
  // Behavioral cluster label — NOT the same as niche. A channel's archetype is
  // a cohort label and may differ from its own niche (documented in model card).
  archetype: string;
  subscriber_count: number;
  mean_views: number;
  // Typical (median) views/video; robust to a few viral uploads, unlike mean.
  median_views: number | null;
  // Total videos on the channel; context for why per-video reach can be high.
  video_count: number;
  // 0..1 engagement-RISK score (heuristic-labeled, not platform-verified fraud).
  fraud_risk: number;
  // Reach-based integration-rate proxy in INR (not earnings). est_cost_inr is the
  // midpoint of a (low, high) range from the niche sponsored-CPM band × median reach.
  est_cost_inr: number;
  est_cost_low_inr: number;
  est_cost_high_inr: number;
}

async function getJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    throw new Error(`API ${res.status} on ${path}`);
  }
  return (await res.json()) as T;
}

export const apiBase = () => BASE;

export const getStats = () => getJSON<Stats>("/stats");

export const searchCreators = (q: string, limit = 24) =>
  getJSON<CreatorSummary[]>(
    `/creators?q=${encodeURIComponent(q)}&limit=${limit}`,
  );

export interface MatchResult extends CreatorSummary {
  // Re-rank components (each 0..1); final_score is the composite.
  final_score: number;
  cosine: number;
  niche_overlap: number;
  budget_fit: number;
  reach_fit: number;
}

export interface MatchRequest {
  brief: string;
  budget_lakh?: number;
  top_k?: number;
  rerank?: boolean;
  niche_filter?: string | null;
  min_views?: number;
}

export interface MatchResponse {
  results: MatchResult[];
  explainer: string | null;
  search_text: string;
}

export const matchCreators = (req: MatchRequest) =>
  getJSON<MatchResponse>("/match", {
    method: "POST",
    body: JSON.stringify(req),
  });

export interface CreatorDetail extends CreatorSummary {
  country: string | null;
  view_count: number;
  video_count: number;
  days_since_last_upload: number | null;
  median_views: number | null;
  mean_engagement_rate: number | null;
  median_engagement_rate: number | null;
  mean_like_rate: number | null;
  mean_comment_rate: number | null;
  mean_comment_to_like_ratio: number | null;
  mean_duration_seconds: number | null;
  engagement_cv: number | null;
  mean_inter_video_days: number | null;
  std_inter_video_days: number | null;
  videos_last_30d: number | null;
  videos_last_90d: number | null;
  mean_views_last_90d: number | null;
  mean_engagement_rate_last_90d: number | null;
  cluster_id: number | null;
  niche_slope: number | null;
  est_sponsored_cost_inr: number | null;
}

export interface ClusterMedians {
  mean_views: number | null;
  mean_engagement_rate: number | null;
  videos_last_30d: number | null;
  mean_inter_video_days: number | null;
}

export interface PeersResponse {
  niche: string | null;
  cohort_size: number;
  engagement_percentile: number | null;
  cohort_medians: ClusterMedians;
  peers: CreatorSummary[];
}

export interface NicheForecastPoint {
  ds: string;
  yhat: number;
  lo80: number;
  hi80: number;
}

export interface NicheForecast {
  niche: string;
  slope: number | null;
  forecast: NicheForecastPoint[];
}

export const getCreator = (id: string) =>
  getJSON<CreatorDetail>(`/creators/${encodeURIComponent(id)}`);

export const getCreatorPeers = (id: string, k = 10) =>
  getJSON<PeersResponse>(`/creators/${encodeURIComponent(id)}/peers?k=${k}`);

export const getNicheForecast = (niche: string) =>
  getJSON<NicheForecast>(`/niches/${encodeURIComponent(niche)}/forecast`);

export interface NicheSummary {
  niche: string;
  creators: number;
  median_views: number | null;
  median_engagement_rate: number | null;
  slope: number | null;
}

export const getNiches = () => getJSON<NicheSummary[]>("/niches");

export const getNicheCreators = (niche: string, k = 24) =>
  getJSON<CreatorSummary[]>(
    `/niches/${encodeURIComponent(niche)}/creators?k=${k}`,
  );


export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

// Grounded product assistant (see apps/api/chatbot.py). Returns { reply }.
export const chat = (messages: ChatMessage[], context?: Record<string, unknown>) =>
  getJSON<{ reply: string }>("/chat", {
    method: "POST",
    body: JSON.stringify(context ? { messages, context } : { messages }),
  });

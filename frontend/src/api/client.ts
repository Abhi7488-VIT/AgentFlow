import axios, { AxiosError, type AxiosRequestConfig, type InternalAxiosRequestConfig } from 'axios';

// Render's free tier sleeps when idle and the first request after that
// waits through a cold start (measured ~52 s, docs/PERF_BASELINE.md).
// Normal requests time out well before that so a dead connection fails
// fast; cold-start failures get one retry with a long timeout.
const DEFAULT_TIMEOUT_MS = 30_000;
export const COLD_START_TIMEOUT_MS = 90_000;

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api';

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: DEFAULT_TIMEOUT_MS,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Session endpoints that read or set the HttpOnly refresh cookie. The API is
// on another site (Render vs Netlify), so the browser only sends or stores
// that cookie when the request is made withCredentials. Kept separate from
// apiClient so a failing refresh never re-enters the 401 handler below.
const sessionClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: COLD_START_TIMEOUT_MS,
  withCredentials: true,
});

/** Per-request opt-in: safe to send twice (login). Never set it on writes like createWorkflow. */
type ColdStartOptions = AxiosRequestConfig & { coldStartRetry?: boolean };
type RetryableConfig = InternalAxiosRequestConfig & {
  coldStartRetry?: boolean;
  _coldStartRetried?: boolean;
  _authRetried?: boolean;
};

let refreshPromise: Promise<string | null> | null = null;

/**
 * Trade the refresh cookie for a new access token. Single-flight: when
 * several requests hit a 401 at once, they all wait on one refresh instead
 * of each rotating the token. Resolves null when the session is over.
 */
export const refreshAccessToken = (): Promise<string | null> => {
  if (!refreshPromise) {
    refreshPromise = sessionClient
      .post('/auth/refresh')
      .then(({ data }) => {
        localStorage.setItem('token', data.access_token);
        localStorage.setItem('user', JSON.stringify(data.user));
        return data.access_token as string;
      })
      .catch(() => null)
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
};

/** Revoke the refresh token server-side and clear its cookie. Best effort. */
export const logoutSession = async (): Promise<void> => {
  try {
    await sessionClient.post('/auth/logout', null, { timeout: DEFAULT_TIMEOUT_MS });
  } catch {
    // The local session is cleared regardless; the token expires on its own.
  }
};

const endSession = () => {
  localStorage.removeItem('token');
  localStorage.removeItem('user');
  window.location.href = '/login';
};

let wakePromise: Promise<boolean> | null = null;

/**
 * Ping the DB-free liveness endpoint so Render starts waking up while the
 * user is still typing. Shared: concurrent callers wait on one request.
 * Resolves true once the server answered.
 */
export const wakeServer = (): Promise<boolean> => {
  if (!wakePromise) {
    wakePromise = apiClient
      .get('/health', { timeout: COLD_START_TIMEOUT_MS })
      .then(() => true)
      .catch(() => {
        wakePromise = null; // let the next caller try again
        return false;
      });
  }
  return wakePromise;
};

const isColdStartFailure = (error: AxiosError) =>
  error.code === 'ECONNABORTED' ||
  error.code === 'ETIMEDOUT' ||
  !error.response || // network error: instance still booting
  [502, 503, 504].includes(error.response.status);

// Request interceptor to add the auth token header to requests
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as RetryableConfig | undefined;
    const idempotent =
      config && (config.coldStartRetry || ['get', 'head'].includes((config.method || 'get').toLowerCase()));

    // One retry, only for requests that are safe to repeat.
    if (config && idempotent && !config._coldStartRetried && isColdStartFailure(error)) {
      config._coldStartRetried = true;
      config.timeout = COLD_START_TIMEOUT_MS;
      await wakeServer();
      return apiClient.request(config);
    }

    // 401 on an authenticated call: the access token expired. Refresh it
    // silently and replay the request once. A 401 is returned before the
    // route runs, so replaying even a POST cannot do the work twice.
    // Not for the login request itself: a wrong password is a 401 too, and a
    // redirect would reload the page and swallow the error message.
    const isLoginCall = config?.url?.startsWith('/auth/login');
    if (config && error.response?.status === 401 && !isLoginCall) {
      if (!config._authRetried) {
        config._authRetried = true;
        const token = await refreshAccessToken();
        if (token) {
          config.headers.Authorization = `Bearer ${token}`;
          return apiClient.request(config);
        }
      }
      endSession();
    }
    return Promise.reject(error);
  }
);

export const fetchOverview = async () => {
  const { data } = await apiClient.get('/dashboard/overview');
  return data;
};

export const fetchSentiment = async () => {
  const { data } = await apiClient.get('/dashboard/sentiment');
  return data;
};

export const fetchTrends = async () => {
  const { data } = await apiClient.get('/dashboard/trends');
  return data;
};

export const fetchRecentActivity = async () => {
  const { data } = await apiClient.get('/dashboard/recent-activity');
  return data;
};

export const fetchWorkflows = async () => {
  const { data } = await apiClient.get('/workflows/');
  return data;
};

export const createWorkflow = async (payload: { query: string; sources: string[] }) => {
  const { data } = await apiClient.post('/workflows/', payload);
  return data;
};

export const fetchReports = async () => {
  const { data } = await apiClient.get('/reports/');
  return data;
};

export const deleteWorkflow = async (id: string) => {
  const { data } = await apiClient.delete(`/workflows/${id}`);
  return data;
};

export const login = async (data: URLSearchParams) => {
  const res = await apiClient.post('/auth/login', data, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    timeout: COLD_START_TIMEOUT_MS,
    withCredentials: true, // lets the browser store the refresh cookie
    coldStartRetry: true, // logging in twice is harmless
  } as ColdStartOptions);
  return res.data;
};

export const deleteReport = async (id: string) => {
  const { data } = await apiClient.delete(`/reports/${id}`);
  return data;
};

export const demoLogin = async () => {
  const res = await apiClient.post('/auth/demo', null, {
    timeout: COLD_START_TIMEOUT_MS,
    withCredentials: true,
    coldStartRetry: true,
  } as ColdStartOptions);
  return res.data;
};

export interface RagSource {
  id: number;
  text: string;
  metadata: Record<string, unknown>;
  similarity: number | null;
}

export interface RagAnswer {
  answer: string;
  sources: RagSource[];
  confidence: number;
}

export const askData = async (question: string, workflowId: string): Promise<RagAnswer> => {
  const { data } = await apiClient.post('/rag/query', { question, workflow_id: workflowId });
  return data;
};

export const fetchRagStatus = async (workflowId: string): Promise<{ indexed_chunks: number; queryable: boolean }> => {
  const { data } = await apiClient.get(`/rag/status/${workflowId}`);
  return data;
};

// Rebuilds the vector index from the workflow's stored data. Needed when the
// host's disk was wiped (e.g. a free-tier redeploy) but the database survived.
export const reindexWorkflow = async (workflowId: string) => {
  const { data } = await apiClient.post('/rag/index', null, { params: { workflow_id: workflowId } });
  return data;
};

export const fetchHealth = async () => {
  const { data } = await apiClient.get('/monitoring/health');
  return data;
};

export const register = async (data: { email: string; password: string; full_name: string }) => {
  const res = await apiClient.post('/auth/register', data);
  return res.data;
};

export const fetchUsers = async () => {
  const { data } = await apiClient.get('/auth/users');
  return data;
};

export const downloadPdf = async (id: string) => {
  const response = await apiClient.get(`/reports/${id}/export/pdf`, {
    responseType: 'blob',
  });
  return response.data;
};

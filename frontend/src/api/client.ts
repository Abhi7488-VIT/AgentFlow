import axios from 'axios';

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api',
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor to add the auth token header to requests
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response interceptor to handle 401 Unauthorized errors globally
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response && error.response.status === 401) {
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      window.location.href = '/login';
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
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
  });
  return res.data;
};

export const deleteReport = async (id: string) => {
  const { data } = await apiClient.delete(`/reports/${id}`);
  return data;
};

export const demoLogin = async () => {
  const res = await apiClient.post('/auth/demo');
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

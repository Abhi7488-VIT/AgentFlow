import axios from 'axios';

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api',
  headers: {
    'Content-Type': 'application/json',
  },
});

// Since we're skipping auth for this UI increment, we don't need interceptors for tokens yet.
// If we add JWT auth later, we can add a request interceptor here.

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
  const { data } = await apiClient.get('/workflows');
  return data;
};

export const createWorkflow = async (payload: { query: string; sources: string[] }) => {
  const { data } = await apiClient.post('/workflows/', payload);
  return data;
};

export const fetchReports = async () => {
  const { data } = await apiClient.get('/reports');
  return data;
};

export const deleteWorkflow = async (id: string) => {
  const { data } = await apiClient.delete(`/workflows/${id}`);
  return data;
};

export const deleteReport = async (id: string) => {
  const { data } = await apiClient.delete(`/reports/${id}`);
  return data;
};

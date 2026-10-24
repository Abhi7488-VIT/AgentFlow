import { useState } from 'react';
import axios from 'axios';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { demoLogin } from '../api/client';

/** Signs into the shared demo account and opens the dashboard. */
export const useDemoLogin = () => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const navigate = useNavigate();
  const { login } = useAuth();

  const start = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await demoLogin();
      login(data.access_token, data.user);
      navigate('/app');
    } catch (err) {
      const detail = axios.isAxiosError(err) ? err.response?.data?.detail : undefined;
      setError(detail || 'The demo server is waking up. Give it a few seconds and try again.');
    } finally {
      setLoading(false);
    }
  };

  return { start, loading, error };
};

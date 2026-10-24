import { useState, useEffect } from 'react';
import axios from 'axios';
import { Users as UsersIcon, Shield, Mail, Calendar } from 'lucide-react';
import { fetchUsers } from '../api/client';

export const Users = () => {
  const [users, setUsers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);

  const loadUsers = async () => {
    try {
      const data = await fetchUsers();
      setUsers(data || []);
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status === 403) setForbidden(true);
      else console.error("Failed to fetch users", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadUsers();
  }, []);

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold gradient-text">User Management</h1>
          <p className="text-clay-ink-muted mt-1">View and manage registered accounts</p>
        </div>
        <div className="clay-card-blue px-6 py-2 text-sm font-semibold flex items-center gap-2">
          <UsersIcon className="w-5 h-5" />
          {users.length} Users Total
        </div>
      </div>

      <div className="clay-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="clay-table min-w-[800px]">
            <thead>
              <tr>
                <th>User</th>
                <th>Role</th>
                <th>Status</th>
                <th>Joined</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-clay-border">
              {loading ? (
                <tr><td colSpan={4} className="p-8 text-center text-clay-ink-muted">Loading users...</td></tr>
              ) : forbidden ? (
                <tr><td colSpan={4} className="p-8 text-center text-clay-ink-muted">Only admins can view registered accounts.</td></tr>
              ) : users.length === 0 ? (
                <tr><td colSpan={4} className="p-8 text-center text-clay-ink-muted">No users found.</td></tr>
              ) : (
                users.map((u) => (
                  <tr key={u.id} className="transition-colors">
                    <td>
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-2xl bg-clay-blue shadow-[inset_0_2px_3px_rgba(255,255,255,0.3),0_3px_0_0_#2563EB] flex items-center justify-center text-white font-bold shrink-0">
                          {u.full_name?.substring(0, 2).toUpperCase() || 'U'}
                        </div>
                        <div>
                          <p className="font-medium text-clay-ink">{u.full_name || 'Anonymous User'}</p>
                          <div className="flex items-center gap-1 text-sm text-clay-ink-muted">
                            <Mail className="w-3 h-3" />
                            {u.email}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td>
                      <span className={`px-3 py-1 text-xs rounded-full flex items-center gap-1 w-max ${u.role === 'admin' ? 'bg-clay-purple/15 text-clay-purple-dark border-2 border-clay-purple/20' : 'bg-clay-bg text-clay-ink-light border-2 border-clay-border'}`}>
                        {u.role === 'admin' && <Shield className="w-3 h-3" />}
                        <span className="capitalize">{u.role}</span>
                      </span>
                    </td>
                    <td>
                      <div className="flex items-center gap-2">
                        <div className={`w-2 h-2 rounded-full ${u.is_active ? 'bg-clay-green' : 'bg-clay-coral'}`}></div>
                        <span className="capitalize text-clay-ink">{u.is_active ? 'Active' : 'Inactive'}</span>
                      </div>
                    </td>
                    <td className="text-clay-ink-muted">
                      <div className="flex items-center gap-1">
                        <Calendar className="w-3 h-3" />
                        {new Date(u.created_at).toLocaleDateString()}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

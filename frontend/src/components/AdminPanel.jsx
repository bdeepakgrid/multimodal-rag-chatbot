import React, { useState, useEffect } from 'react';
import { Users, Shield, Calendar, Mail, CheckCircle2, AlertCircle, Save } from 'lucide-react';
import { listUsers, updateUserRole } from '../api';

export const AdminPanel = () => {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [savingId, setSavingId] = useState(null);
  const [successMsg, setSuccessMsg] = useState(null);
  const [modifiedRoles, setModifiedRoles] = useState({});

  useEffect(() => {
    loadUsers();
  }, []);

  const loadUsers = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await listUsers();
      setUsers(data.users || []);
    } catch (err) {
      setError(err.message || 'Failed to load users');
    } finally {
      setLoading(false);
    }
  };

  const handleRoleChange = (userId, newRole) => {
    setModifiedRoles((prev) => ({ ...prev, [userId]: newRole }));
  };

  const handleSaveRole = async (userId) => {
    const newRole = modifiedRoles[userId];
    if (!newRole) return;

    try {
      setSavingId(userId);
      await updateUserRole(userId, newRole);
      
      // Update local state
      setUsers((prev) =>
        prev.map((u) => (u.id === userId ? { ...u, role: newRole } : u))
      );
      
      // Clear modification
      setModifiedRoles((prev) => {
        const next = { ...prev };
        delete next[userId];
        return next;
      });
      
      setSuccessMsg('Role updated successfully. Active sessions for this user were invalidated.');
      setTimeout(() => setSuccessMsg(null), 5000);
    } catch (err) {
      setError(`Failed to update role: ${err.message}`);
    } finally {
      setSavingId(null);
    }
  };

  return (
    <div className="main-content" style={{ padding: 'var(--space-6)', overflowY: 'auto' }}>
      <div style={{ maxWidth: '1000px', margin: '0 auto' }}>
        
        <div style={{ marginBottom: 'var(--space-6)' }}>
          <h2 style={{ fontSize: '20px', fontWeight: 600, margin: '0 0 var(--space-2) 0', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Users size={20} style={{ color: 'var(--accent-base)' }} />
            User Management
          </h2>
          <p style={{ color: 'var(--text-secondary)', margin: 0, fontSize: '14px' }}>
            Manage user roles and access permissions. Changing a user's role will require them to log in again.
          </p>
        </div>

        {error && (
          <div style={{ backgroundColor: 'var(--status-error-bg)', color: 'var(--status-error)', padding: 'var(--space-3) var(--space-4)', borderRadius: 'var(--radius-base)', fontSize: '14px', marginBottom: 'var(--space-4)', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <AlertCircle size={16} />
            {error}
          </div>
        )}

        {successMsg && (
          <div style={{ backgroundColor: 'var(--status-success-bg)', color: 'var(--status-success)', padding: 'var(--space-3) var(--space-4)', borderRadius: 'var(--radius-base)', fontSize: '14px', marginBottom: 'var(--space-4)', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <CheckCircle2 size={16} />
            {successMsg}
          </div>
        )}

        <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-lg)', overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '14px' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-base)' }}>
                <th style={{ padding: 'var(--space-3) var(--space-4)', fontWeight: 500, color: 'var(--text-secondary)' }}>User</th>
                <th style={{ padding: 'var(--space-3) var(--space-4)', fontWeight: 500, color: 'var(--text-secondary)' }}>Role</th>
                <th style={{ padding: 'var(--space-3) var(--space-4)', fontWeight: 500, color: 'var(--text-secondary)' }}>Joined</th>
                <th style={{ padding: 'var(--space-3) var(--space-4)', fontWeight: 500, color: 'var(--text-secondary)', width: '120px' }}>Action</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan="4" style={{ padding: 'var(--space-6)', textAlign: 'center', color: 'var(--text-tertiary)' }}>
                    Loading users...
                  </td>
                </tr>
              ) : users.length === 0 ? (
                <tr>
                  <td colSpan="4" style={{ padding: 'var(--space-6)', textAlign: 'center', color: 'var(--text-tertiary)' }}>
                    No users found.
                  </td>
                </tr>
              ) : (
                users.map((user) => {
                  const currentRole = modifiedRoles[user.id] || user.role;
                  const isModified = !!modifiedRoles[user.id] && modifiedRoles[user.id] !== user.role;
                  const date = new Date(user.created_at).toLocaleDateString();

                  return (
                    <tr key={user.id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                      <td style={{ padding: 'var(--space-3) var(--space-4)' }}>
                        <div style={{ display: 'flex', flexDirection: 'column' }}>
                          <span style={{ fontWeight: 500, color: 'var(--text-main)' }}>{user.username}</span>
                          <span style={{ fontSize: '12px', color: 'var(--text-tertiary)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                            <Mail size={12} /> {user.email}
                          </span>
                        </div>
                      </td>
                      <td style={{ padding: 'var(--space-3) var(--space-4)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <Shield size={14} style={{ color: currentRole === 'admin' ? 'var(--status-error)' : currentRole === 'reviewer' ? 'var(--status-success)' : 'var(--text-tertiary)' }} />
                          <select
                            value={currentRole}
                            onChange={(e) => handleRoleChange(user.id, e.target.value)}
                            style={{ 
                              background: 'var(--bg-base)', 
                              border: '1px solid var(--border-base)', 
                              color: 'var(--text-main)', 
                              padding: '4px 8px',
                              borderRadius: 'var(--radius-sm)',
                              outline: 'none',
                              fontSize: '13px',
                              cursor: 'pointer'
                            }}
                          >
                            <option value="technician">Technician</option>
                            <option value="reviewer">Reviewer</option>
                            <option value="admin">Admin</option>
                          </select>
                        </div>
                      </td>
                      <td style={{ padding: 'var(--space-3) var(--space-4)', color: 'var(--text-secondary)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <Calendar size={14} /> {date}
                        </div>
                      </td>
                      <td style={{ padding: 'var(--space-3) var(--space-4)' }}>
                        {isModified ? (
                          <button
                            onClick={() => handleSaveRole(user.id)}
                            disabled={savingId === user.id}
                            style={{
                              padding: '6px 12px',
                              borderRadius: 'var(--radius-sm)',
                              background: 'var(--accent-base)',
                              color: 'white',
                              border: 'none',
                              cursor: 'pointer',
                              display: 'flex',
                              alignItems: 'center',
                              gap: '6px',
                              fontSize: '12px',
                              fontWeight: 500,
                              opacity: savingId === user.id ? 0.7 : 1
                            }}
                          >
                            <Save size={14} />
                            {savingId === user.id ? 'Saving...' : 'Save'}
                          </button>
                        ) : (
                          <span style={{ color: 'var(--text-tertiary)', fontSize: '13px' }}>Saved</span>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

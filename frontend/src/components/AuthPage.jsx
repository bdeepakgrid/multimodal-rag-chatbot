import React, { useState } from 'react';
import { User, Lock, Mail, LogIn, UserPlus, Database } from 'lucide-react';
import { loginUser, signupUser } from '../api';

export const AuthPage = ({ onAuthSuccess }) => {
  const [tab, setTab] = useState('login'); // 'login' | 'signup'
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      let result;
      if (tab === 'login') {
        result = await loginUser(username, password);
      } else {
        result = await signupUser(username, email, password);
      }
      if (onAuthSuccess) onAuthSuccess(result.user);
    } catch (err) {
      setError(err.message || 'Authentication failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        width: '100vw',
        backgroundColor: 'var(--bg-app)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 'var(--space-6)',
        color: 'var(--text-main)',
        fontFamily: 'var(--font-body)',
      }}
    >
      <div
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 'var(--radius-lg)',
          width: '100%',
          maxWidth: '440px',
          padding: 'var(--space-8)',
          boxShadow: 'var(--shadow-lg)',
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', marginBottom: 'var(--space-8)' }}>
          <div style={{ background: 'var(--accent-subtle)', padding: '12px', borderRadius: '12px', marginBottom: 'var(--space-4)' }}>
            <Database size={28} style={{ color: 'var(--accent-base)' }} />
          </div>
          <h1 className="chrome-text" style={{ fontSize: '24px', margin: '0 0 var(--space-2) 0', textAlign: 'center' }}>
            Multimodal Agentic RAG
          </h1>
          <p style={{ fontSize: '14px', color: 'var(--text-secondary)', margin: 0, textAlign: 'center' }}>
            Sign in to access your diagnostic tools and conversations.
          </p>
        </div>

        <div style={{ display: 'flex', gap: 'var(--space-2)', marginBottom: 'var(--space-6)', background: 'var(--bg-base)', padding: '4px', borderRadius: 'var(--radius-md)' }}>
          <button
            onClick={() => { setTab('login'); setError(''); }}
            style={{
              flex: 1,
              padding: '10px 16px',
              borderRadius: 'var(--radius-sm)',
              border: 'none',
              background: tab === 'login' ? 'var(--bg-surface)' : 'transparent',
              color: tab === 'login' ? 'var(--accent-base)' : 'var(--text-tertiary)',
              fontWeight: 600,
              fontSize: '14px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px',
              transition: 'all var(--transition-fast)',
              boxShadow: tab === 'login' ? 'var(--shadow-sm)' : 'none',
            }}
          >
            <LogIn size={16} /> Login
          </button>
          <button
            onClick={() => { setTab('signup'); setError(''); }}
            style={{
              flex: 1,
              padding: '10px 16px',
              borderRadius: 'var(--radius-sm)',
              border: 'none',
              background: tab === 'signup' ? 'var(--bg-surface)' : 'transparent',
              color: tab === 'signup' ? 'var(--accent-base)' : 'var(--text-tertiary)',
              fontWeight: 600,
              fontSize: '14px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px',
              transition: 'all var(--transition-fast)',
              boxShadow: tab === 'signup' ? 'var(--shadow-sm)' : 'none',
            }}
          >
            <UserPlus size={16} /> Sign Up
          </button>
        </div>

        {error && (
          <div style={{ backgroundColor: 'var(--status-error-bg)', color: 'var(--status-error)', padding: 'var(--space-3) var(--space-4)', borderRadius: 'var(--radius-base)', fontSize: '14px', marginBottom: 'var(--space-6)', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontWeight: 600 }}>Error:</span> {error}
          </div>
        )}

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
          <div>
            <label style={{ fontSize: '13px', fontWeight: 500, color: 'var(--text-secondary)', display: 'block', marginBottom: 'var(--space-1)' }}>
              Username
            </label>
            <div style={{ display: 'flex', alignItems: 'center', background: 'var(--bg-base)', borderRadius: 'var(--radius-base)', padding: '10px 14px', border: '1px solid var(--border-base)', transition: 'border-color var(--transition-fast)' }} className="input-container-focus">
              <User size={16} style={{ color: 'var(--text-tertiary)', marginRight: '10px' }} />
              <input
                type="text"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Enter your username"
                style={{ background: 'transparent', border: 'none', color: 'var(--text-main)', width: '100%', outline: 'none', fontSize: '14px' }}
              />
            </div>
          </div>

          {tab === 'signup' && (
            <div>
              <label style={{ fontSize: '13px', fontWeight: 500, color: 'var(--text-secondary)', display: 'block', marginBottom: 'var(--space-1)' }}>
                Email
              </label>
              <div style={{ display: 'flex', alignItems: 'center', background: 'var(--bg-base)', borderRadius: 'var(--radius-base)', padding: '10px 14px', border: '1px solid var(--border-base)' }} className="input-container-focus">
                <Mail size={16} style={{ color: 'var(--text-tertiary)', marginRight: '10px' }} />
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="name@example.com"
                  style={{ background: 'transparent', border: 'none', color: 'var(--text-main)', width: '100%', outline: 'none', fontSize: '14px' }}
                />
              </div>
            </div>
          )}

          <div>
            <label style={{ fontSize: '13px', fontWeight: 500, color: 'var(--text-secondary)', display: 'block', marginBottom: 'var(--space-1)' }}>
              Password
            </label>
            <div style={{ display: 'flex', alignItems: 'center', background: 'var(--bg-base)', borderRadius: 'var(--radius-base)', padding: '10px 14px', border: '1px solid var(--border-base)' }} className="input-container-focus">
              <Lock size={16} style={{ color: 'var(--text-tertiary)', marginRight: '10px' }} />
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter your password"
                style={{ background: 'transparent', border: 'none', color: 'var(--text-main)', width: '100%', outline: 'none', fontSize: '14px' }}
              />
            </div>
          </div>



          <button
            type="submit"
            disabled={loading}
            style={{
              marginTop: 'var(--space-2)',
              padding: '14px',
              borderRadius: 'var(--radius-base)',
              background: 'var(--accent-base)',
              color: 'white',
              fontWeight: 600,
              border: 'none',
              cursor: 'pointer',
              fontSize: '15px',
              opacity: loading ? 0.7 : 1,
              transition: 'background var(--transition-fast)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px'
            }}
            onMouseOver={(e) => e.currentTarget.style.background = 'var(--accent-hover)'}
            onMouseOut={(e) => e.currentTarget.style.background = 'var(--accent-base)'}
          >
            {loading ? 'Processing...' : (tab === 'login' ? 'Sign In' : 'Create Account')}
          </button>
        </form>
      </div>
    </div>
  );
};

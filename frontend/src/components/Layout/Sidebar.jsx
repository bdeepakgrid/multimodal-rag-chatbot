import React from 'react';
import { Database, Hash, Plus, UploadCloud, FileStack, Trash2, Shield, LogOut, User, Users } from 'lucide-react';
import { logoutUser } from '../../api';


export const Sidebar = ({
  threads,
  activeThreadId,
  onSelectThread,
  onNewThread,
  onDeleteThread,
  onOpenIngestion,
  onOpenDocuments,
  onOpenAdmin,
  activeView,
  currentUser,   // { username, role, ... } passed from App
}) => {
  const role = currentUser?.role;
  const isAdmin    = role === 'admin';
  const isReviewer = role === 'reviewer' || isAdmin;

  const handleLogout = () => {
    logoutUser();
    window.location.reload();
  };

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <Database size={16} style={{ color: 'var(--accent-base)' }} />
        <span className="chrome-text" style={{ fontSize: '13px', fontWeight: 600 }}>Multimodal Agentic RAG</span>
      </div>

      <div className="sidebar-content">
        <div>
          <button className="nav-item" style={{ width: '100%', textAlign: 'left' }} onClick={onNewThread}>
            <Plus size={14} />
            <span>New Conversation</span>
          </button>

          {/* Ingest Documents — ADMIN only */}
          {isAdmin && (
            <button
              className={`nav-item ${activeView === 'ingest' ? 'active' : ''}`}
              style={{ width: '100%', textAlign: 'left' }}
              onClick={onOpenIngestion}
            >
              <UploadCloud size={14} />
              <span>Ingest Documents</span>
            </button>
          )}

          {/* Document Inventory — REVIEWER and ADMIN */}
          {isReviewer && (
            <button
              className={`nav-item ${activeView === 'documents' ? 'active' : ''}`}
              style={{ width: '100%', textAlign: 'left' }}
              onClick={onOpenDocuments}
            >
              <FileStack size={14} />
              <span>Document Inventory</span>
            </button>
          )}

          {/* User Management — ADMIN only */}
          {isAdmin && (
            <button
              className={`nav-item ${activeView === 'admin' ? 'active' : ''}`}
              style={{ width: '100%', textAlign: 'left' }}
              onClick={onOpenAdmin}
            >
              <Users size={14} />
              <span>User Management</span>
            </button>
          )}
        </div>

        <div style={{ marginTop: 'var(--space-2)' }}>
          <div className="sidebar-section-title">Conversations</div>

          {threads.length === 0 && (
            <div className="nav-item" style={{ color: 'var(--text-tertiary)' }}>
              <span>No conversations yet</span>
            </div>
          )}

          {threads.map((thread) => (
            <div
              key={thread.id}
              className={`nav-item ${activeView === 'chat' && thread.id === activeThreadId ? 'active' : ''}`}
              style={{ justifyContent: 'space-between', cursor: 'pointer' }}
              onClick={() => onSelectThread(thread.id)}
            >
              <span style={{ display: 'flex', alignItems: 'center', gap: '8px', overflow: 'hidden' }}>
                <Hash size={14} style={{ flexShrink: 0 }} />
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{thread.title}</span>
              </span>
              <button
                onClick={(e) => { e.stopPropagation(); onDeleteThread(thread.id); }}
                title="Delete conversation"
                style={{ color: 'var(--text-tertiary)', flexShrink: 0 }}
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))}
        </div>
      </div>

      {currentUser && (
        <div style={{ padding: 'var(--space-4)', borderTop: '1px solid var(--border-subtle)', background: 'var(--bg-base)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', overflow: 'hidden' }}>
              <div style={{ width: '32px', height: '32px', borderRadius: '50%', background: 'var(--accent-subtle)', color: 'var(--accent-base)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                <User size={16} />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-main)', whiteSpace: 'nowrap', textOverflow: 'ellipsis', overflow: 'hidden' }}>
                  {currentUser.username}
                </span>
                <span style={{ fontSize: '11px', color: 'var(--text-tertiary)', textTransform: 'capitalize', display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <Shield size={10} />
                  {currentUser.role}
                </span>
              </div>
            </div>
            <button
              onClick={handleLogout}
              title="Logout"
              className="icon-btn"
              style={{ flexShrink: 0 }}
            >
              <LogOut size={16} />
            </button>
          </div>
        </div>
      )}
    </aside>
  );
};

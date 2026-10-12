import React from 'react';
import { FileText, Link, X } from 'lucide-react';
import { rawDocumentUrl } from '../../api';

export const ContextPanel = ({ sources, confidence, onClose }) => {
  if (!sources || sources.length === 0) {
    return (
      <aside className="context-panel">
        <div className="context-header">
          <span className="chrome-text" style={{ fontSize: '12px', fontWeight: 600 }}>RETRIEVED CONTEXT</span>
        </div>
        <div className="context-content" style={{ justifyContent: 'center', alignItems: 'center', color: 'var(--text-tertiary)' }}>
          <div style={{ textAlign: 'center', fontSize: '13px' }}>
            <FileText size={24} style={{ margin: '0 auto 8px auto', opacity: 0.5 }} />
            No context retrieved for<br/>the current interaction.
          </div>
        </div>
      </aside>
    );
  }

  return (
    <aside className="context-panel">
      <div className="context-header" style={{ justifyContent: 'space-between' }}>
        <span className="chrome-text" style={{ fontSize: '12px', fontWeight: 600 }}>RETRIEVED CONTEXT</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          {typeof confidence === 'number' && (
            <span className="confidence-badge" title="Overall answer confidence">
              {(confidence * 100).toFixed(0)}% confidence
            </span>
          )}
          <button onClick={onClose} style={{ color: 'var(--text-tertiary)' }}>
            <X size={16} />
          </button>
        </div>
      </div>

      <div className="context-content">
        {sources.map((s, idx) => (
          <div key={idx} className="source-card">
            <div className="source-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <FileText size={14} style={{ color: 'var(--text-secondary)' }} />
                <span className="source-title">{s.file} {s.page ? `(p. ${s.page})` : ''}</span>
              </div>
            </div>
            <div className="source-snippet">
              {s.snippet}
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '8px' }}>
              <a
                href={rawDocumentUrl(s.tenant_id, s.file)}
                target="_blank"
                rel="noreferrer"
                style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '11px', color: 'var(--accent-base)', fontWeight: 500 }}
              >
                <Link size={12} /> View Source
              </a>
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
};

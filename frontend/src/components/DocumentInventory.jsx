import React, { useCallback, useEffect, useState } from 'react';
import { FileText, Link, Trash2, AlertCircle, Loader2 } from 'lucide-react';
import { listAllDocuments, deleteDocument, rawDocumentUrl } from '../api';

export const DocumentInventory = ({ canDelete = false }) => {
  const [documents, setDocuments] = useState([]);
  const [totalChunks, setTotalChunks] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [deletingKey, setDeletingKey] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listAllDocuments();
      setDocuments(data.documents || []);
      setTotalChunks(data.total_chunks || 0);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleDelete = async (doc) => {
    const key = `${doc.tenant_id}::${doc.source_file}`;
    if (!window.confirm(`Remove "${doc.source_file}" (${doc.chunk_count} chunks) from the "${doc.tenant_id}" knowledge base?`)) {
      return;
    }
    setDeletingKey(key);
    try {
      const result = await deleteDocument(doc.tenant_id, doc.source_file);
      setDocuments((prev) => prev.filter((d) => `${d.tenant_id}::${d.source_file}` !== key));
      setTotalChunks((prev) => Math.max(0, prev - (result.deleted_chunks || doc.chunk_count)));
    } catch (e) {
      setError(e.message);
    } finally {
      setDeletingKey(null);
    }
  };

  return (
    <div className="admin-layout">
      <div className="admin-card" style={{ maxWidth: '760px' }}>
        <div className="admin-header">
          <h2>Document Inventory</h2>
          <p>Every document currently indexed and searchable across all knowledge bases.</p>
        </div>

        {loading && (
          <div className="empty-state">
            <Loader2 size={20} className="animate-spin" style={{ marginBottom: '8px' }} />
            <div>Loading documents…</div>
          </div>
        )}

        {error && !loading && (
          <div className="result-banner error">
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
              <AlertCircle size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
              <span>Failed to load documents: {error}</span>
            </div>
          </div>
        )}

        {!loading && !error && documents.length === 0 && (
          <div className="empty-state">
            <FileText size={24} style={{ margin: '0 auto 8px auto', opacity: 0.5 }} />
            <div>No documents have been ingested yet.</div>
          </div>
        )}

        {!loading && !error && documents.length > 0 && (
          <>
            <div className="doc-table-summary">
              <span><strong>{documents.length}</strong> document{documents.length === 1 ? '' : 's'}</span>
              <span><strong>{totalChunks}</strong> total chunks</span>
            </div>

            {documents.map((doc) => {
              const key = `${doc.tenant_id}::${doc.source_file}`;
              const isDeleting = deletingKey === key;
              return (
                <div className="doc-row" key={key}>
                  <div className="doc-row-main">
                    <FileText size={16} style={{ color: 'var(--text-tertiary)', flexShrink: 0, marginTop: '2px' }} />
                    <div style={{ minWidth: 0 }}>
                      <div className="doc-row-name">{doc.source_file}</div>
                      <div className="doc-row-meta">
                        {doc.chunk_count} chunk{doc.chunk_count === 1 ? '' : 's'} · {doc.source_type}
                        {doc.tags.length > 0 && <> · tags: {doc.tags.join(', ')}</>}
                        {doc.last_updated && <> · updated {new Date(doc.last_updated).toLocaleDateString()}</>}
                      </div>
                      <div className="doc-row-tenant">{doc.tenant_id}</div>
                    </div>
                  </div>

                  <div className="doc-row-actions">
                    <a href={rawDocumentUrl(doc.tenant_id, doc.source_file)} target="_blank" rel="noreferrer">
                      <Link size={12} /> View
                    </a>
                    {canDelete && (
                      <button onClick={() => handleDelete(doc)} disabled={isDeleting} title="Delete document">
                        {isDeleting ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </>
        )}
      </div>
    </div>
  );
};

import React, { useState, useRef } from 'react';
import { UploadCloud, FileText, Loader2, CheckCircle2, AlertCircle } from 'lucide-react';
import { ingestFiles } from '../api';

export const IngestionPanel = () => {
  const [tenantId, setTenantId] = useState('default');

  const [tags, setTags] = useState('');
  const [files, setFiles] = useState([]);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [result, setResult] = useState(null);
  
  const fileInputRef = useRef(null);

  const handleDragEnter = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      setFiles(Array.from(e.dataTransfer.files));
    }
  };

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      setFiles(Array.from(e.target.files));
    }
  };

  const handleUpload = async () => {
    if (files.length === 0 || isUploading) return;
    
    setIsUploading(true);
    setResult(null);

    try {
      const data = await ingestFiles(tenantId || 'default', files, tags);

      const chunks = data.chunks_created || 0;
      const sources = data.source_files || [];
      const errors = data.errors || [];
      
      let msg = `Successfully ingested ${chunks} chunks from ${sources.length} files.`;
      if (errors.length > 0) {
        msg += `\nErrors: ${errors.join('; ')}`;
      }
      
      setResult({ success: errors.length === 0, message: msg });

      if (errors.length === 0) {
        setFiles([]);
        if (fileInputRef.current) fileInputRef.current.value = '';
      }
    } catch (error) {
      setResult({ success: false, message: `Error: ${error.message}` });
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="admin-layout">
      <div className="admin-card">
        <div className="admin-header">
          <h2>Document Ingestion</h2>
          <p>Upload files (PDF, XLSX, CSV, TXT, MD, DOCX) to index them into your knowledge base.</p>
        </div>

        <div className="input-group">
          <label className="input-label">Tenant ID</label>
          <input 
            type="text" 
            className="text-input" 
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
            placeholder="default"
          />
        </div>

        <div className="input-group">
          <label className="input-label">Tags (comma-separated)</label>
          <input 
            type="text" 
            className="text-input" 
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            placeholder="e.g. motor, manual, overheat"
          />
        </div>

        <div 
          className={`dropzone ${isDragging ? 'active' : ''}`}
          onDragEnter={handleDragEnter}
          onDragLeave={handleDragLeave}
          onDragOver={handleDragOver}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
        >
          <input 
            type="file" 
            multiple 
            ref={fileInputRef}
            onChange={handleFileChange}
            style={{ display: 'none' }}
            accept=".pdf,.xlsx,.csv,.txt,.md,.docx"
          />
          <UploadCloud size={48} className="dropzone-icon" />
          <div style={{ color: 'var(--text-main)', fontWeight: 500, marginBottom: '0.5rem' }}>
            Click to upload or drag and drop
          </div>
          <div style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>
            Supported formats: PDF, XLSX, CSV, TXT, MD, DOCX
          </div>
        </div>

        {files.length > 0 && (
          <div className="file-list">
            {files.map((f, i) => (
              <div key={i} className="file-item">
                <FileText size={16} style={{ color: 'var(--text-muted)' }} />
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {f.name}
                </span>
                <span style={{ color: 'var(--text-muted)' }}>
                  {(f.size / 1024).toFixed(1)} KB
                </span>
              </div>
            ))}
          </div>
        )}

        <button 
          className="primary-btn"
          onClick={handleUpload}
          disabled={files.length === 0 || isUploading}
        >
          {isUploading ? (
            <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem' }}>
              <Loader2 className="animate-spin" size={20} />
              Uploading...
            </span>
          ) : (
            'Start Ingestion'
          )}
        </button>

        {result && (
          <div className={`result-banner ${result.success ? '' : 'error'} animate-slide-up`}>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.75rem' }}>
              {result.success ? (
                <CheckCircle2 style={{ color: '#10B981', flexShrink: 0, marginTop: '2px' }} size={20} />
              ) : (
                <AlertCircle style={{ color: '#EF4444', flexShrink: 0, marginTop: '2px' }} size={20} />
              )}
              <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.4 }}>
                {result.message}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
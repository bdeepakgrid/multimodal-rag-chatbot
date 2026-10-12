import React, { useEffect, useRef, useState } from 'react';
import { ArrowUp, ImagePlus, X } from 'lucide-react';

export const DiagnosticInputBar = ({ input, setInput, image, setImage, handleSend, isLoading }) => {
  const textareaRef = useRef(null);
  const fileInputRef = useRef(null);
  const [previewUrl, setPreviewUrl] = useState(null);

  useEffect(() => {
    if (!image) {
      setPreviewUrl(null);
      return undefined;
    }
    const url = URL.createObjectURL(image);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [image]);

  const handleInput = (e) => {
    setInput(e.target.value);
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
    }
  };

  const handleImage = (event) => {
    const [file] = event.target.files;
    if (!file) return;
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) return;
    setImage(file);
    event.target.value = '';
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="input-area-wrapper">
      <div className="input-container">
        <input ref={fileInputRef} type="file" accept="image/png,image/jpeg,image/webp" onChange={handleImage} hidden />

        {image && (
          <div className="attachment-pill">
            <img className="attachment-thumbnail" src={previewUrl} alt="Selected diagnostic attachment" />
            <span className="attachment-name">{image.name}</span>
            <button type="button" className="icon-btn attachment-remove" onClick={() => setImage(null)} title="Remove image">
              <X size={15} />
            </button>
          </div>
        )}

        <textarea
          ref={textareaRef}
          className="chat-input"
          value={input}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder="Describe the diagnostic issue..."
          rows={1}
        />

        <div className="input-footer">
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <button type="button" className="icon-btn" onClick={() => fileInputRef.current?.click()} disabled={isLoading} title="Attach diagnostic image">
              <ImagePlus size={17} />
            </button>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div className="shortcut-hint" style={{ opacity: 0.7 }}>
              <span className="kbd">Enter</span>
              <span>to send</span>
            </div>
            <button
              className="primary-action-btn"
              onClick={handleSend}
              disabled={(!input.trim() && !image) || isLoading}
            >
              Send <ArrowUp size={14} />
            </button>
          </div>
        </div>

      </div>
    </div>
  );
};

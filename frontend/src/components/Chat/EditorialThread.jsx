import React, { useState, useEffect } from 'react';
import { User, Cpu, ChevronDown, ChevronRight, Search, Check, Plus, ArrowUp } from 'lucide-react';
import { CitationPill } from './CitationPill';

const parseMarkdownWithCitations = (text) => {
  if (!text) return { __html: '' };
  
  // This is a naive parser for the sake of the example.
  // In a real app, you'd use marked.js or react-markdown with custom renderers.
  let html = text
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>')
    .replace(/\n/g, '<br/>');
    
  return { __html: html };
};

const SuggestionChips = ({ message, onSuggestionSelect, disabled }) => {
  const [customContext, setCustomContext] = useState('');
  const locked = Boolean(message.selectedSuggestionId);
  const isDisabled = disabled || locked;

  const submitCustom = () => {
    const value = customContext.trim();
    if (!value || isDisabled) return;
    onSuggestionSelect({ customContext: value });
  };

  return (
    <div className="suggestion-chip-group" aria-label="Clarifying context options">
      {message.suggestions.map((suggestion) => {
        const selected = message.selectedSuggestionId === suggestion.id;
        return (
          <button
            key={suggestion.id}
            type="button"
            className={`suggestion-chip ${selected ? 'selected' : ''}`}
            onClick={() => onSuggestionSelect(suggestion)}
            disabled={isDisabled}
            title={suggestion.context}
          >
            {selected && <Check size={13} />}
            <span>{suggestion.label}</span>
          </button>
        );
      })}

      {!locked ? (
        <form
          className="suggestion-chip custom-context-chip"
          onSubmit={(e) => {
            e.preventDefault();
            submitCustom();
          }}
        >
          <input
            value={customContext}
            onChange={(e) => setCustomContext(e.target.value)}
            placeholder="Add context"
            disabled={disabled}
            autoFocus
          />
          <button type="submit" disabled={!customContext.trim() || disabled} title="Use this context">
            <ArrowUp size={13} />
          </button>
        </form>
      ) : (
        <button
          type="button"
          className={`suggestion-chip custom-trigger ${message.selectedSuggestionId === 'custom-context' ? 'selected' : ''}`}
          disabled={isDisabled}
          title="Add your own context"
        >
          {message.selectedSuggestionId === 'custom-context' ? <Check size={13} /> : <Plus size={13} />}
          <span>{message.selectedSuggestionLabel === 'More context' ? 'More context selected' : 'Add context'}</span>
        </button>
      )}
    </div>
  );
};

export const EditorialThreadItem = ({ message, onCitationClick, onSuggestionSelect, suggestionsDisabled }) => {
  const isUser = message.role === 'user';
  const [showSteps, setShowSteps] = useState(false);

  // Get time in HH:MM format
  const timeStr = new Date(message.timestamp || 0).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  return (
    <div className="thread-item animate-fade-in">
      <div className="avatar-col">
        <div className={`thread-avatar ${!isUser ? 'system' : ''}`}>
          {isUser ? <User size={16} /> : <Cpu size={16} />}
        </div>
      </div>
      
      <div className="content-col">
        <div className="thread-meta">
          <span className="thread-author">{isUser ? 'Engineer (You)' : 'Diagnostics Assistant'}</span>
          <span className="thread-time">{timeStr}</span>
        </div>
        
        <div className="thread-body">
          {isUser ? (
            <div>
              <div>{message.content}</div>
              {message.imagePreview && <img className="message-image" src={message.imagePreview} alt={message.imageName || 'Diagnostic attachment'} />}
              {message.imageName && !message.imagePreview && <div className="message-image-name">Attached image: {message.imageName}</div>}
            </div>
          ) : (
            <div>
              {message.agentSteps && message.agentSteps.length > 0 && (
                <div className="agent-trace">
                  <button className="agent-trace-toggle" onClick={() => setShowSteps((v) => !v)}>
                    {showSteps ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                    <Search size={12} />
                    <span>
                      {message.agentSteps.length === 1
                        ? 'Searched knowledge base once'
                        : `Searched knowledge base ${message.agentSteps.length} times`}
                    </span>
                  </button>
                  {showSteps && (
                    <div className="agent-trace-steps">
                      {message.agentSteps.map((step, idx) => (
                        <div key={idx} className="agent-trace-step">
                          <span className="agent-trace-query">"{step.query}"</span>
                          <span className="agent-trace-result">
                            {step.results_found} result{step.results_found === 1 ? '' : 's'}
                            {typeof step.best_score === 'number' && ` · best score ${step.best_score.toFixed(2)}`}
                          </span>
                          {step.thought && <div className="agent-trace-thought">{step.thought}</div>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              <span dangerouslySetInnerHTML={parseMarkdownWithCitations(message.content)} />
              
              {message.sources && message.sources.length > 0 && (
                <div style={{ marginTop: '8px' }}>
                  {message.sources.map((src, idx) => (
                    <CitationPill
                      key={idx}
                      source={src}
                      index={idx + 1}
                      onClick={() => onCitationClick(message.sources, message.confidence)}
                    />
                  ))}
                </div>
              )}

              {message.suggestions && message.suggestions.length > 0 && (
                <SuggestionChips
                  message={message}
                  onSuggestionSelect={onSuggestionSelect}
                  disabled={suggestionsDisabled}
                />
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export const RetrievalSkeleton = () => {
  const messages = [
    'Thinking...',
    'Searching knowledge base...',
    'Reranking technical manuals...',
    'Generating diagnostic report...',
  ];
  const [idx, setIdx] = useState(0);

  useEffect(() => {
    const t = setInterval(() => setIdx((i) => (i + 1) % messages.length), 700);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="thread-item">
      <div className="avatar-col">
        <div className="thread-avatar system">
          <Cpu size={16} />
        </div>
      </div>
      <div className="content-col">
        <div className="thread-meta">
          <span className="thread-author">Diagnostics Assistant</span>
        </div>
        <div className="thread-body" style={{ marginTop: '8px' }}>
          <div className="retrieval-step">
            <div className="step-icon" />
            <span>{messages[idx]}</span>
          </div>
        </div>
      </div>
    </div>
  );
};

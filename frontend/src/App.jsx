import React, { useState, useRef, useEffect } from 'react';
import { Sidebar } from './components/Layout/Sidebar';
import { ContextPanel } from './components/Layout/ContextPanel';
import { EditorialThreadItem, RetrievalSkeleton } from './components/Chat/EditorialThread';
import { DiagnosticInputBar } from './components/Chat/DiagnosticInputBar';
import { IngestionPanel } from './components/IngestionPanel';
import { DocumentInventory } from './components/DocumentInventory';
import { AdminPanel } from './components/AdminPanel';
import { AuthPage } from './components/AuthPage';
import { sendChatMessage, getCurrentUser, setAuthToken } from './api';
import './App.css';

const BASE_THREADS_KEY = 'rag_threads';

// Per-user thread storage key — isolates conversation history between accounts.
const threadsKey = (user) =>
  user?.username ? `${BASE_THREADS_KEY}_${user.username}` : BASE_THREADS_KEY;

const WELCOME_MESSAGE = {
  role: 'system',
  content: 'Welcome to the Diagnostics Assistant. Describe the issue and I\'ll search across the full knowledge base for you.',
  timestamp: Date.now(),
};

const makeThread = () => ({
  id: crypto.randomUUID(),
  title: 'New Conversation',
  createdAt: Date.now(),
  messages: [WELCOME_MESSAGE],
});

function loadThreads(user) {
  try {
    const saved = localStorage.getItem(threadsKey(user));
    if (saved) {
      const parsed = JSON.parse(saved);
      if (Array.isArray(parsed) && parsed.length > 0) {
        // Blob URLs are only valid for the current browser session. Keep the
        // attachment name in persisted history without restoring a dead preview.
        return parsed.map((thread) => ({
          ...thread,
          messages: thread.messages?.map((message) => ({ ...message, imagePreview: null })) || [],
        }));
      }
    }
  } catch (e) {
    console.error('Failed to parse saved threads', e);
  }
  return [makeThread()];
}

const titleFor = (messages) => {
  const firstUser = messages.find((m) => m.role === 'user');
  if (!firstUser) return 'New Conversation';
  return firstUser.content.length > 42 ? `${firstUser.content.slice(0, 42)}…` : firstUser.content;
};

const buildContextualQuery = (query, suggestion) => {
  if (suggestion.id?.startsWith('candidate-')) {
    return suggestion.label;
  }
  if (suggestion.id?.startsWith('feedback-')) {
    return suggestion.label.toLowerCase();
  }

  const customContext = suggestion.customContext?.trim();
  const selectedContext = suggestion.context || customContext;
  const searchHint = suggestion.searchHint || suggestion.search_hint || customContext;

  return [
    query,
    '',
    `Selected context: ${suggestion.label}.`,
    selectedContext ? `Use this as the search angle: ${selectedContext}` : '',
    searchHint ? `Search hints: ${searchHint}` : '',
  ]
    .filter(Boolean)
    .join('\n');
};

function App() {
  const [currentUser, setCurrentUser] = useState(getCurrentUser);
  const [threads, setThreads] = useState(() => loadThreads(getCurrentUser()));
  const [activeThreadId, setActiveThreadId] = useState(() => loadThreads(getCurrentUser())[0].id);
  const [input, setInput] = useState('');
  const [image, setImage] = useState(null);
  const [isLoading, setIsLoading] = useState(false);

  const [activeSources, setActiveSources] = useState([]);
  const [activeConfidence, setActiveConfidence] = useState(null);
  const [showContextPanel, setShowContextPanel] = useState(false);
  const [view, setView] = useState('chat'); // 'chat' | 'ingest' | 'documents' | 'admin'

  const messagesEndRef = useRef(null);

  const activeThread = threads.find((t) => t.id === activeThreadId) ?? threads[0];

  useEffect(() => {
    localStorage.setItem(threadsKey(currentUser), JSON.stringify(threads));
  }, [threads, currentUser]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [activeThread?.messages, isLoading]);

  const updateThread = (id, updater) => {
    setThreads((prev) => prev.map((t) => (t.id === id ? updater(t) : t)));
  };

  const runChat = async ({ displayQuery, backendQuery, threadId, attachedImage = null }) => {
    setIsLoading(true);

    try {
      const data = await sendChatMessage(backendQuery, threadId, attachedImage);

      updateThread(threadId, (t) => {
        const responseMessage = {
          role: 'system',
          content: data.answer || 'No response.',
          timestamp: Date.now(),
          sources: data.sources || [],
          confidence: data.confidence,
          agentSteps: data.agent_steps || [],
          suggestions: data.suggestions || [],
          suggestionQuery: data.suggestions?.length ? displayQuery : null,
          selectedSuggestionId: null,
        };

        const messages = [...t.messages, responseMessage];
        return { ...t, messages, title: t.title === 'New Conversation' ? titleFor(messages) : t.title };
      });

      if (data.sources && data.sources.length > 0) {
        setActiveSources(data.sources);
        setActiveConfidence(data.confidence);
        setShowContextPanel(true);
      }
    } catch (error) {
      updateThread(threadId, (t) => ({
        ...t,
        messages: [
          ...t.messages,
          { role: 'system', content: `**Error:** Failed to reach the backend. ${error.message}`, timestamp: Date.now() },
        ],
      }));
    } finally {
      setIsLoading(false);
    }
  };

  const handleSend = async () => {
    if ((!input.trim() && !image) || isLoading || !activeThread) return;

    const userMsg = input.trim() || 'Analyze this equipment image.';
    const threadId = activeThread.id;
    const attachedImage = image;

    updateThread(threadId, (t) => {
      const messages = [...t.messages, {
        role: 'user', content: userMsg, timestamp: Date.now(),
        imagePreview: attachedImage ? URL.createObjectURL(attachedImage) : null,
        imageName: attachedImage?.name || null,
      }];
      return { ...t, messages, title: t.title === 'New Conversation' ? titleFor(messages) : t.title };
    });
    setInput('');
    setImage(null);

    await runChat({ displayQuery: userMsg, backendQuery: userMsg, threadId, attachedImage });
  };

  const handleSuggestionSelect = async (threadId, messageIndex, suggestion, suggestionMessage) => {
    if (isLoading || !suggestionMessage) return;

    if (!suggestionMessage?.suggestionQuery || suggestionMessage.selectedSuggestionId) return;

    const selectedSuggestion = suggestion.id
      ? suggestion
      : {
          id: 'custom-context',
          label: 'More context',
          customContext: suggestion.customContext,
        };
    const backendQuery = buildContextualQuery(suggestionMessage.suggestionQuery, selectedSuggestion);

    updateThread(threadId, (t) => ({
      ...t,
      messages: t.messages.map((msg, idx) =>
        idx === messageIndex
          ? {
              ...msg,
              selectedSuggestionId: selectedSuggestion.id,
              selectedSuggestionLabel: selectedSuggestion.label,
            }
          : msg
      ),
    }));

    await runChat({
      displayQuery: suggestionMessage.suggestionQuery,
      backendQuery,
      threadId,
    });
  };

  const handleCitationClick = (sources, confidence) => {
    setActiveSources(sources);
    setActiveConfidence(confidence ?? null);
    setShowContextPanel(true);
  };

  const handleNewThread = () => {
    const t = makeThread();
    setThreads((prev) => [t, ...prev]);
    setActiveThreadId(t.id);
    setShowContextPanel(false);
    setView('chat');
  };

  const handleDeleteThread = (id) => {
    setThreads((prev) => {
      const next = prev.filter((t) => t.id !== id);
      if (next.length === 0) {
        const t = makeThread();
        if (id === activeThreadId) setActiveThreadId(t.id);
        return [t];
      }
      if (id === activeThreadId) setActiveThreadId(next[0].id);
      return next;
    });
  };

  if (!currentUser) {
    return (
      <AuthPage
        onAuthSuccess={(user) => {
          setCurrentUser(user);
          // Load this user's personal thread history (isolated by username).
          const userThreads = loadThreads(user);
          setThreads(userThreads);
          setActiveThreadId(userThreads[0].id);
        }}
      />
    );
  }

  return (
    <div className="layout-root">
      <Sidebar
        threads={threads}
        activeThreadId={activeThreadId}
        currentUser={currentUser}
        onSelectThread={(id) => {
          setActiveThreadId(id);
          setView('chat');
        }}
        onNewThread={handleNewThread}
        onDeleteThread={handleDeleteThread}
        onOpenIngestion={() => setView('ingest')}
        onOpenDocuments={() => setView('documents')}
        onOpenAdmin={() => setView('admin')}
        activeView={view}
      />

      <main className="main-panel">
        <header className="main-header">
          <div className="chrome-text" style={{ fontSize: '15px', fontWeight: 600 }}>
            {view === 'ingest' && 'Ingest Documents'}
            {view === 'documents' && 'Document Inventory'}
            {view === 'admin' && 'User Management'}
            {view === 'chat' && (activeThread?.title || 'Diagnostic Thread')}
          </div>
        </header>

        {view === 'ingest' && <IngestionPanel />}
        {view === 'documents' && <DocumentInventory canDelete={currentUser?.role === 'admin'} />}
        {view === 'admin' && <AdminPanel />}
        {view === 'chat' && (
          <div className="main-content">
            <div className="thread-container">
              {activeThread?.messages.map((msg, idx) => (
                <EditorialThreadItem
                  key={idx}
                  message={msg}
                  onCitationClick={handleCitationClick}
                  onSuggestionSelect={(suggestion) => handleSuggestionSelect(activeThread.id, idx, suggestion, msg)}
                  suggestionsDisabled={isLoading}
                />
              ))}

              {isLoading && <RetrievalSkeleton />}

              <div ref={messagesEndRef} style={{ height: '40px' }} />
            </div>

            <DiagnosticInputBar input={input} setInput={setInput} image={image} setImage={setImage} handleSend={handleSend} isLoading={isLoading} />
          </div>
        )}
      </main>

      {showContextPanel && view === 'chat' && (
        <ContextPanel
          sources={activeSources}
          confidence={activeConfidence}
          onClose={() => setShowContextPanel(false)}
        />
      )}

    </div>
  );
}

export default App;

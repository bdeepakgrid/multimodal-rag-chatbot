import React from 'react';
import { FileText } from 'lucide-react';

export const CitationPill = ({ source, index, onClick }) => {
  return (
    <button className="citation-pill" onClick={onClick} title={source.file}>
      <FileText size={10} />
      <span>[{index}]</span>
    </button>
  );
};

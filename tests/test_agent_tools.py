import asyncio

import pytest

from rag.tools import RetrievalToolbox


class FakeRetriever:
    def __init__(self):
        self.qdrant_store = self

    async def retrieve_across_all(self, query):
        self.last_query = query
        return []

    def list_tenant_ids(self):
        return []


def test_toolbox_dispatches_named_tools():
    retriever = FakeRetriever()
    toolbox = RetrievalToolbox(retriever)

    result = asyncio.run(toolbox.call("search_error_code", "A.042"))

    assert result.tool_name == "search_error_code"
    assert "A.042" in retriever.last_query
    assert "search_knowledge_base" in toolbox.descriptions


def test_toolbox_rejects_unknown_tools():
    toolbox = RetrievalToolbox(FakeRetriever())

    with pytest.raises(ValueError):
        asyncio.run(toolbox.call("delete_everything", "all"))


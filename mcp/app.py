"""
MCP Server for the Danish Legal RAG system.

Exposes the RAG functionality as MCP tools so it can be used from
Claude Desktop or any other MCP-compatible client.

Tools:
  legal_search  - Semantic search for relevant legal provisions
  legal_answer  - Ask a question and get a structured answer with references

Configuration for Claude Desktop (add to claude_desktop_config.json):
{
  "mcpServers": {
    "danish-legal-rag": {
      "command": "docker",
      "args": ["exec", "-i", "danish-legal-rag-mcp-1", "python", "/app/mcp/server.py"]
    }
  }
}

Or for direct connection via HTTP SSE (when using mcp[sse]):
{
  "mcpServers": {
    "danish-legal-rag": {
      "url": "http://localhost:8001/mcp"
    }
  }
}
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

import httpx

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

sys.path.insert(0, "/app")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

API_BASE_URL = os.environ.get("API_BASE_URL", "http://api:8000")

server = Server("danish-legal-rag")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """Declare available MCP tools."""
    return [
        Tool(
            name="legal_search",
            description=(
                "Søg semantisk i dansk juridisk database. "
                "Returnerer relevante lovbestemmelser med præcise referencer (lov, §, stk.). "
                "Dækker Afskrivningsloven og Årsregnskabsloven."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Søgeforespørgsel på dansk (naturligt sprog)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maksimalt antal resultater (standard: 5)",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 20,
                    },
                    "filter_law": {
                        "type": "string",
                        "description": "Valgfrit: filtrer på lovkode (AFL, ARL)",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="legal_answer",
            description=(
                "Stil et juridisk spørgsmål og få et struktureret svar med "
                "forklaring, præcise juridiske referencer, citater og kildehenvisninger. "
                "Svarene baseres udelukkende på indlæste danske lovtekster. "
                "Dækker dansk skatte- og regnskabsret, herunder afskrivninger og immaterielle aktiver."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Juridisk spørgsmål på dansk",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Antal kilder at hente (standard: 5)",
                        "default": 5,
                    },
                },
                "required": ["question"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle MCP tool calls."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        if name == "legal_search":
            response = await client.post(
                f"{API_BASE_URL}/search",
                json={
                    "query": arguments["query"],
                    "limit": arguments.get("limit", 5),
                    "filter_law": arguments.get("filter_law"),
                },
            )
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            if not results:
                return [TextContent(
                    type="text",
                    text="Ingen relevante lovbestemmelser fundet for den givne søgning.",
                )]

            lines = [f"**Søgeresultater for: '{arguments['query']}'**\n"]
            for i, ref in enumerate(results, 1):
                lines.append(
                    f"{i}. **{ref.get('citation_label', 'Ukendt')}**\n"
                    f"   Lov: {ref.get('law', '')}\n"
                    f"   Score: {ref.get('score', 0):.3f}\n"
                    f"   Tekst: {ref.get('quote', '')[:300]}...\n"
                    f"   Kilde: {ref.get('source_url', 'Ikke tilgængelig')}\n"
                )

            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "legal_answer":
            response = await client.post(
                f"{API_BASE_URL}/ask",
                json={
                    "question": arguments["question"],
                    "limit": arguments.get("limit", 5),
                },
            )
            response.raise_for_status()
            data = response.json()

            lines = [
                f"## Svar på: '{data['question']}'\n",
                f"**Model:** {data.get('model_used', 'ukendt')}\n",
                "---\n",
                data.get("answer", "Intet svar"),
                "\n\n---\n\n## Juridiske referencer\n",
            ]

            for i, ref in enumerate(data.get("references", []), 1):
                lines.append(
                    f"\n### {i}. {ref.get('citation_label', '')}\n"
                    f"- **Lov:** {ref.get('law', '')}\n"
                    f"- **Paragraf:** {ref.get('section', '')}\n"
                    + (f"- **Stk.:** {ref.get('subsection', '')}\n" if ref.get('subsection') else "")
                    + (f"- **Overskrift:** {ref.get('title', '')}\n" if ref.get('title') else "")
                    + f"- **Relevans:** {ref.get('score', 0):.3f}\n"
                    + f"- **Kilde:** {ref.get('source_url', 'Ikke tilgængelig')}\n"
                    + f"\n> {ref.get('quote', '')[:500]}\n"
                )

            return [TextContent(type="text", text="\n".join(lines))]

        else:
            return [TextContent(type="text", text=f"Ukendt tool: {name}")]


async def main():
    """Run the MCP server over stdio."""
    logger.info("Starting Danish Legal RAG MCP server...")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

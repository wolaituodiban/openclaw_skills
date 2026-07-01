import asyncio
import os
from typing import Optional
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from dotenv import load_dotenv

load_dotenv()  # load environment variables from .env


def print_result(result):
    print('\n\n')
    for item in result:
        if item[0] == 'content':
            for content in item[1]:
                if content.type == 'text':
                    print(content.text, '\n')


class MCPClient:
    def __init__(self):
        # Initialize session and client objects
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
    # methods will go here

    async def connect_to_server(self):
        """Connect to an MCP server

        Args:
            server_script_path: Path to the server script (.py or .js)
        """
        cwd = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        print(cwd)

        server_params = StdioServerParameters(
            command='python',
            args=["-m", "scripts.mcp_server"],
            cwd=cwd
        )

        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))

        await self.session.initialize()

        # List available tools
        response = await self.session.list_tools()
        tools = response.tools
        print("\nConnected to server with tools:", [tool.name for tool in tools])

    async def cleanup(self):
        """Clean up resources"""
        await self.exit_stack.aclose()


async def main():
    client = MCPClient()
    try:
        await client.connect_to_server()
    finally:
        await client.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
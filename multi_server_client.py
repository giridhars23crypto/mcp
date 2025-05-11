import asyncio
import sys
from typing import Optional, Dict, Any, List
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import datetime, timedelta
import sqlite3

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from openai import OpenAI
from dotenv import load_dotenv
import anyio

load_dotenv()

@dataclass
class ToolState:
    tool_name: str
    required_params: Dict[str, Any]
    collected_params: Dict[str, Any]
    description: str
    server_name: str

class MultiServerClient:
    def __init__(self):
        self.flight_session: Optional[ClientSession] = None
        self.calendar_session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.openai = OpenAI()
        self.current_tool_state: Optional[ToolState] = None
        self.conversation_history = []
        self.available_tools = {}

    async def connect_to_servers(self, flight_server_path: str, calendar_url: str):
        """Connect to both flight booking and calendar servers"""
        try:
            # Connect to flight booking server
            server_params = StdioServerParameters(
                command="python",
                args=[flight_server_path],
                env=None
            )

            # Create a new exit stack for this connection
            self.exit_stack = AsyncExitStack()
            
            # Connect to flight server
            stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
            self.flight_session = await self.exit_stack.enter_async_context(
                ClientSession(stdio_transport[0], stdio_transport[1])
            )
            await self.flight_session.initialize()

            # Get flight booking tools
            flight_response = await self.flight_session.list_tools()
            for tool in flight_response.tools:
                self.available_tools[tool.name] = {
                    "description": tool.description,
                    "input_schema": tool.inputSchema,
                    "session": self.flight_session,
                    "server_name": "flight"
                }

            # Connect to calendar server
            sse_transport = await self.exit_stack.enter_async_context(sse_client(calendar_url))
            read_stream, write_stream = sse_transport
            self.calendar_session = await self.exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await self.calendar_session.initialize()

            # Get calendar tools
            calendar_response = await self.calendar_session.list_tools()
            for tool in calendar_response.tools:
                self.available_tools[tool.name] = {
                    "description": tool.description,
                    "input_schema": tool.inputSchema,
                    "session": self.calendar_session,
                    "server_name": "calendar"
                }

            print("\nConnected to servers with tools:", list(self.available_tools.keys()))
        except Exception as e:
            await self.cleanup()
            raise e

    def _create_tool_state(self, tool_name: str, tool_info: dict) -> ToolState:
        """Create a new tool state for collecting parameters"""
        required_params = {}
        for param_name, param_info in tool_info["input_schema"]["properties"].items():
            if param_name not in tool_info["input_schema"].get("required", []):
                continue
            required_params[param_name] = {
                "type": param_info.get("type"),
                "description": param_info.get("description", "")
            }
        
        return ToolState(
            tool_name=tool_name,
            required_params=required_params,
            collected_params={},
            description=tool_info["description"],
            server_name=tool_info["server_name"]
        )

    def _get_missing_params(self) -> list:
        """Get list of parameters still needed for the current tool"""
        if not self.current_tool_state:
            return []
        return [
            param for param in self.current_tool_state.required_params
            if param not in self.current_tool_state.collected_params
        ]

    def _extract_parameters(self, text: str) -> Dict[str, Any]:
        """Extract parameters from user's text response"""
        params = {}
        lines = text.split('\n')
        for line in lines:
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip().lower()
                value = value.strip()
                params[key] = value
        return params

    async def _create_calendar_event(self, flight_info: Dict[str, Any]) -> str:
        """Create a calendar event for the flight booking"""
        if not self.calendar_session:
            return "Calendar server not connected"

        # Get flight details from database
        conn = sqlite3.connect('flight_booking.db')
        cursor = conn.cursor()
        
        try:
            # Query flight details using flight_id
            cursor.execute("""
                SELECT f.flight_number, f.departure_time, f.arrival_time,
                       dep.airport_code as dep_airport, arr.airport_code as arr_airport
                FROM flights f
                JOIN airports dep ON f.departure_airport_id = dep.airport_id
                JOIN airports arr ON f.arrival_airport_id = arr.airport_id
                WHERE f.flight_id = ?
            """, (flight_info['flight_id'],))
            
            flight_details = cursor.fetchone()
            if not flight_details:
                return "Error: Flight details not found"
            
            flight_number, departure_time, arrival_time, departure_airport, arrival_airport = flight_details
            
            # Format the event details
            summary = f"Flight {flight_number} from {departure_airport} to {arrival_airport}"
            description = f"Flight booking from {departure_airport} to {arrival_airport}"
            
            # Create calendar event with new parameter format
            result = await self.calendar_session.call_tool(
                "google_calendar_create_detailed_event",
                {
                    "instructions": f"Create a calendar event for {summary}",
                    "summary": summary,
                    "description": description,
                    "start__dateTime": departure_time,
                    "end__dateTime": arrival_time

                }
            )
            return result.content
            
        except Exception as e:
            return f"Error creating calendar event: {str(e)}"
        finally:
            conn.close()

    async def process_query(self, query: str) -> str:
        """Process a query using OpenAI and available tools"""
        # Format tools for OpenAI
        tools = [{
            "type": "function",
            "function": {
                "name": name,
                "description": info["description"],
                "parameters": info["input_schema"]
            }
        } for name, info in self.available_tools.items()]

        # Initial system message to instruct the model
        messages = [
            {
                "role": "system",
                "content": "You are a helpful flight booking assistant. You have access to tools for searching flights, booking flights, managing bookings, and calendar integration. Use these tools to help users with their flight-related needs."
            },
            {
                "role": "user",
                "content": query
            }
        ]

        # If we're in the middle of collecting parameters
        if self.current_tool_state:
            missing_params = self._get_missing_params()
            if missing_params:
                # Extract parameters from user's response
                new_params = self._extract_parameters(query)
                self.current_tool_state.collected_params.update(new_params)
                
                # Check if we have all required parameters
                if all(param in self.current_tool_state.collected_params 
                      for param in self.current_tool_state.required_params):
                    # Execute the tool call
                    tool_info = self.available_tools[self.current_tool_state.tool_name]
                    result = await tool_info["session"].call_tool(
                        self.current_tool_state.tool_name,
                        self.current_tool_state.collected_params
                    )
                    
                    # If this was a flight booking, create calendar event
                    if self.current_tool_state.tool_name == "book_flight":
                        await self._create_calendar_event(self.current_tool_state.collected_params)
                        # Add tool call and result to messages
                        messages.append({
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [{
                                "id": "flight_booking",
                                "type": "function",
                                "function": {
                                    "name": "book_flight",
                                    "arguments": json.dumps(self.current_tool_state.collected_params)
                                }
                            }]
                        })
                        messages.append({
                            "role": "tool",
                            "tool_call_id": "flight_booking",
                            "content": result.content
                        })
                    else:
                        # Add tool call and result to messages
                        messages.append({
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [{
                                "id": "tool_call",
                                "type": "function",
                                "function": {
                                    "name": self.current_tool_state.tool_name,
                                    "arguments": json.dumps(self.current_tool_state.collected_params)
                                }
                            }]
                        })
                        messages.append({
                            "role": "tool",
                            "tool_call_id": "tool_call",
                            "content": result.content
                        })
                    
                    # Get final response from OpenAI
                    final_response = self.openai.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=messages,
                        tools=tools
                    )
                    
                    self.current_tool_state = None
                    return final_response.choices[0].message.content
                else:
                    # Still need more parameters
                    remaining = [param for param in missing_params 
                               if param not in new_params]
                    return f"Please provide the following information:\n" + \
                           "\n".join(f"- {param}" for param in remaining)

        # Initial OpenAI API call
        response = self.openai.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=1000,
            messages=messages,
            tools=tools
        )

        # Process response
        message = response.choices[0].message
        
        # Check if there's a tool call
        if message.tool_calls:
            tool_call = message.tool_calls[0]
            tool_name = tool_call.function.name
            tool_info = self.available_tools[tool_name]
            
            # Create new tool state
            self.current_tool_state = self._create_tool_state(tool_name, tool_info)
            
            # Parse the function arguments
            import json
            tool_args = json.loads(tool_call.function.arguments)
            
            # Check if we have all required parameters
            if all(param in tool_args for param in self.current_tool_state.required_params):
                # Execute tool call immediately
                result = await tool_info["session"].call_tool(tool_name, tool_args)
                
                # Add tool call and result to messages
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": tool_call.function.arguments
                        }
                    }]
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result.content
                })
                
                # If this was a flight booking, create calendar event but don't add to messages
                if tool_name == "book_flight":
                    # print(tool_args)
                    await self._create_calendar_event(tool_args)
                
                # Get final response from OpenAI
                final_response = self.openai.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    tools=tools
                )
                
                self.current_tool_state = None
                return final_response.choices[0].message.content
            else:
                # Need to collect more parameters
                missing = [param for param in self.current_tool_state.required_params 
                         if param not in tool_args]
                return f"To {self.current_tool_state.description}, I need the following information:\n" + \
                       "\n".join(f"- {param}" for param in missing)
        else:
            # Regular text response
            return message.content

    async def chat_loop(self):
        """Run an interactive chat loop"""
        print("\nMulti-Server Client Started!")
        print("Type your queries or 'quit' to exit.")
        print("Example queries:")
        print("- Search for flights from JFK to LAX on May 15th")
        print("- Book a flight")
        print("- Check my bookings")
        print("- Cancel a booking")

        while True:
            try:
                query = input("\nQuery: ").strip()

                if query.lower() == 'quit':
                    break

                response = await self.process_query(query)
                print("\nAI: " + response)

            except Exception as e:
                print(f"\nError: {str(e)}")
                self.current_tool_state = None  # Reset tool state on error

    async def cleanup(self):
        """Clean up resources"""
        try:
            # Clear references to sessions
            self.flight_session = None
            self.calendar_session = None
            
            # Close the exit stack if it exists
            if hasattr(self, 'exit_stack') and self.exit_stack is not None:
                try:
                    await self.exit_stack.aclose()
                except Exception as e:
                    print(f"Warning: Error during cleanup: {str(e)}")
                finally:
                    self.exit_stack = None
        except Exception as e:
            print(f"Warning: Error during cleanup: {str(e)}")

async def main():
    if len(sys.argv) < 3:
        print("Usage: python multi_server_client.py <flight_server_path> <calendar_server_url>")
        sys.exit(1)

    client = MultiServerClient()
    try:
        await client.connect_to_servers(sys.argv[1], sys.argv[2])
        await client.chat_loop()
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
    except Exception as e:
        print(f"\nError: {str(e)}")
    finally:
        await client.cleanup()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProgram terminated by user")
    except Exception as e:
        print(f"\nFatal error: {str(e)}") 
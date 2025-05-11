import sqlite3
from datetime import datetime
from typing import List, Optional
from dataclasses import dataclass
from mcp.server.fastmcp import FastMCP, Context

# Create MCP server
mcp = FastMCP("Flight Booking System")

@dataclass
class FlightInfo:
    flight_id: int
    flight_number: str
    airline_name: str
    departure_airport: str
    arrival_airport: str
    departure_time: str
    arrival_time: str
    price: float
    available_seats: int

@dataclass
class BookingInfo:
    booking_id: int
    flight_number: str
    username: str
    booking_date: str
    status: str

def get_db_connection():
    return sqlite3.connect('flight_booking.db')

@mcp.tool()
def search_flights(
    departure_airport: Optional[str] = None,
    arrival_airport: Optional[str] = None,
    date: Optional[str] = None
) -> List[FlightInfo]:
    """Search for available flights based on departure, arrival, and date"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
    SELECT f.flight_id, f.flight_number, a.airline_name,
           dep.airport_code as dep_airport, arr.airport_code as arr_airport,
           f.departure_time, f.arrival_time, f.price, f.available_seats
    FROM flights f
    JOIN airlines a ON f.airline_id = a.airline_id
    JOIN airports dep ON f.departure_airport_id = dep.airport_id
    JOIN airports arr ON f.arrival_airport_id = arr.airport_id
    WHERE 1=1
    """
    params = []
    
    if departure_airport:
        query += " AND dep.airport_code = ?"
        params.append(departure_airport.upper())
    if arrival_airport:
        query += " AND arr.airport_code = ?"
        params.append(arrival_airport.upper())
    if date:
        query += " AND date(f.departure_time) = date(?)"
        params.append(date)
    
    cursor.execute(query, params)
    flights = cursor.fetchall()
    
    return [
        FlightInfo(
            flight_id=row[0],
            flight_number=row[1],
            airline_name=row[2],
            departure_airport=row[3],
            arrival_airport=row[4],
            departure_time=row[5],
            arrival_time=row[6],
            price=row[7],
            available_seats=row[8]
        )
        for row in flights
    ]

@mcp.tool()
def book_flight(flight_id: int, username: str) -> str:
    """Book a flight for a user"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Check if flight exists and has available seats
        cursor.execute("""
            SELECT available_seats FROM flights WHERE flight_id = ?
        """, (flight_id,))
        result = cursor.fetchone()
        
        if not result:
            return "Error: Flight not found"
        
        available_seats = result[0]
        if available_seats <= 0:
            return "Error: No seats available on this flight"
        
        # Get user_id
        cursor.execute("SELECT user_id FROM users WHERE username = ?", (username,))
        user_result = cursor.fetchone()
        if not user_result:
            return "Error: User not found"
        
        user_id = user_result[0]
        
        # Create booking
        cursor.execute("""
            INSERT INTO bookings (user_id, flight_id, status)
            VALUES (?, ?, 'CONFIRMED')
        """, (user_id, flight_id))
        
        # Update available seats
        cursor.execute("""
            UPDATE flights 
            SET available_seats = available_seats - 1
            WHERE flight_id = ?
        """, (flight_id,))
        
        conn.commit()
        return f"Successfully booked flight {flight_id} for user {username}"
        
    except Exception as e:
        conn.rollback()
        return f"Error booking flight: {str(e)}"

@mcp.tool()
def cancel_booking(booking_id: int) -> str:
    """Cancel a flight booking"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Get booking details
        cursor.execute("""
            SELECT b.booking_id, b.flight_id, b.status
            FROM bookings b
            WHERE b.booking_id = ?
        """, (booking_id,))
        
        booking = cursor.fetchone()
        if not booking:
            return "Error: Booking not found"
        
        if booking[2] == 'CANCELLED':
            return "Error: Booking is already cancelled"
        
        # Update booking status
        cursor.execute("""
            UPDATE bookings 
            SET status = 'CANCELLED'
            WHERE booking_id = ?
        """, (booking_id,))
        
        # Increment available seats
        cursor.execute("""
            UPDATE flights 
            SET available_seats = available_seats + 1
            WHERE flight_id = ?
        """, (booking[1],))
        
        conn.commit()
        return f"Successfully cancelled booking {booking_id}"
        
    except Exception as e:
        conn.rollback()
        return f"Error cancelling booking: {str(e)}"

@mcp.tool()
def get_user_bookings(username: str) -> List[BookingInfo]:
    """Get all bookings for a user"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT b.booking_id, f.flight_number, u.username, b.booking_date, b.status
        FROM bookings b
        JOIN users u ON b.user_id = u.user_id
        JOIN flights f ON b.flight_id = f.flight_id
        WHERE u.username = ?
        ORDER BY b.booking_date DESC
    """, (username,))
    
    bookings = cursor.fetchall()
    
    return [
        BookingInfo(
            booking_id=row[0],
            flight_number=row[1],
            username=row[2],
            booking_date=row[3],
            status=row[4]
        )
        for row in bookings
    ]

if __name__ == "__main__":
    mcp.run() 
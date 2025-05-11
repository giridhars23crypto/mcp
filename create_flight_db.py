import sqlite3
from datetime import datetime, timedelta
import random

def create_database():
    # Connect to SQLite database (creates it if it doesn't exist)
    conn = sqlite3.connect('flight_booking.db')
    cursor = conn.cursor()

    # Create tables
    cursor.executescript('''
        -- Airlines table
        CREATE TABLE IF NOT EXISTS airlines (
            airline_id INTEGER PRIMARY KEY,
            airline_name TEXT NOT NULL,
            airline_code TEXT NOT NULL UNIQUE
        );

        -- Airports table
        CREATE TABLE IF NOT EXISTS airports (
            airport_id INTEGER PRIMARY KEY,
            airport_code TEXT NOT NULL UNIQUE,
            airport_name TEXT NOT NULL,
            city TEXT NOT NULL,
            country TEXT NOT NULL
        );

        -- Flights table
        CREATE TABLE IF NOT EXISTS flights (
            flight_id INTEGER PRIMARY KEY,
            airline_id INTEGER,
            flight_number TEXT NOT NULL,
            departure_airport_id INTEGER,
            arrival_airport_id INTEGER,
            departure_time DATETIME NOT NULL,
            arrival_time DATETIME NOT NULL,
            price DECIMAL(10,2) NOT NULL,
            available_seats INTEGER NOT NULL,
            FOREIGN KEY (airline_id) REFERENCES airlines(airline_id),
            FOREIGN KEY (departure_airport_id) REFERENCES airports(airport_id),
            FOREIGN KEY (arrival_airport_id) REFERENCES airports(airport_id)
        );

        -- Users table
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        -- Bookings table
        CREATE TABLE IF NOT EXISTS bookings (
            booking_id INTEGER PRIMARY KEY,
            user_id INTEGER,
            flight_id INTEGER,
            booking_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (flight_id) REFERENCES flights(flight_id)
        );
    ''')

    # Insert sample data
    # Airlines
    airlines = [
        (1, 'Delta Airlines', 'DL'),
        (2, 'United Airlines', 'UA'),
        (3, 'American Airlines', 'AA'),
        (4, 'Southwest Airlines', 'WN')
    ]
    cursor.executemany('INSERT INTO airlines VALUES (?, ?, ?)', airlines)

    # Airports
    airports = [
        (1, 'JFK', 'John F. Kennedy International', 'New York', 'USA'),
        (2, 'LAX', 'Los Angeles International', 'Los Angeles', 'USA'),
        (3, 'LHR', 'Heathrow Airport', 'London', 'UK'),
        (4, 'CDG', 'Charles de Gaulle Airport', 'Paris', 'France'),
        (5, 'SFO', 'San Francisco International', 'San Francisco', 'USA')
    ]
    cursor.executemany('INSERT INTO airports VALUES (?, ?, ?, ?, ?)', airports)

    # Generate sample flights
    flights = []
    flight_number = 1000
    for airline_id in range(1, 5):
        for _ in range(5):  # 5 flights per airline
            departure_airport = random.choice(airports)[0]
            arrival_airport = random.choice([a[0] for a in airports if a[0] != departure_airport])
            
            # Generate random departure time in the next 7 days
            departure_time = datetime.now() + timedelta(days=random.randint(1, 7))
            # Flight duration between 2-8 hours
            flight_duration = timedelta(hours=random.randint(2, 8))
            arrival_time = departure_time + flight_duration
            
            price = round(random.uniform(200, 1000), 2)
            available_seats = random.randint(50, 200)
            
            flights.append((
                flight_number,
                airline_id,
                f"{airlines[airline_id-1][2]}{flight_number}",
                departure_airport,
                arrival_airport,
                departure_time,
                arrival_time,
                price,
                available_seats
            ))
            flight_number += 1

    cursor.executemany('''
        INSERT INTO flights (flight_id, airline_id, flight_number, departure_airport_id, 
                           arrival_airport_id, departure_time, arrival_time, price, available_seats)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', flights)

    # Sample users
    users = [
        (1, 'john_doe', 'john@example.com', 'hashed_password_1'),
        (2, 'jane_smith', 'jane@example.com', 'hashed_password_2'),
        (3, 'bob_wilson', 'bob@example.com', 'hashed_password_3')
    ]
    cursor.executemany('INSERT INTO users VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)', users)

    # Sample bookings
    bookings = [
        (1, 1, 1000, datetime.now(), 'CONFIRMED'),
        (2, 2, 1001, datetime.now(), 'CONFIRMED'),
        (3, 3, 1002, datetime.now(), 'PENDING')
    ]
    cursor.executemany('INSERT INTO bookings VALUES (?, ?, ?, ?, ?)', bookings)

    # Commit changes and close connection
    conn.commit()
    conn.close()

if __name__ == '__main__':
    create_database()
    print("Database created successfully with sample data!") 
# Dynamic Route Optimizer

A real-time vehicle route optimization system using Amazon Location Service and DynamoDB for ride-sharing applications.

## Features

- **Dynamic Route Optimization**: Optimal pickup/dropoff sequencing with flexible routing
- **Time-Based Filtering**: Interactive datetime filtering for route planning
- **Multi-Request Handling**: Vehicles can handle multiple passengers (up to 11 requests per vehicle)
- **Beautiful Visualization**: Interactive Folium maps with numbered stops and route lines
- **Real-Time Updates**: Flask web interface with auto-reload capabilities
- **AWS Integration**: Uses DynamoDB for data storage and Amazon Location Service for routing

## Architecture

- **Backend**: Python Flask server with route optimization logic
- **Frontend**: Dynamic Folium-generated HTML maps
- **Database**: DynamoDB tables (requests, stops, vehicles)
- **Routing**: Amazon Location Service for optimal route calculation
- **Visualization**: Interactive maps with vehicle tracking and stop sequencing

## Files

- `web_server.py` - Flask web application (main entry point)
- `dynamic_route_optimizer.py` - Core optimization logic and map generation
- `vehicle_route_optimizer.py` - Basic route optimizer (legacy)
- `requirements_web.txt` - Python dependencies

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements_web.txt
   ```

2. Configure AWS credentials and ensure DynamoDB tables exist:
   - `requests` table
   - `stops` table  
   - `vehicles` table

3. Set up Amazon Location Service route calculator named `MyRouteCalculator`

4. Run the application:
   ```bash
   python web_server.py
   ```

5. Open browser at `http://localhost:5000`

## Usage

- **View All Routes**: Load the page to see all optimized routes
- **Filter by Time**: Use datetime controls to filter requests by pickup time
- **Interactive Map**: Click markers to see request details and stop information
- **Real-Time Updates**: Modify code and refresh browser to see changes

## Route Optimization

The system uses intelligent routing that:
- Prioritizes pickup times and passenger waiting constraints
- Allows flexible pickup/dropoff sequences (not just all pickups first)
- Groups multiple requests at the same stop location
- Respects 30-minute waiting time windows
- Minimizes total travel time and distance

## Map Features

- **Numbered Stops**: Sequential stop ordering with pickup/dropoff indicators
- **Vehicle Markers**: Car icons showing vehicle start positions
- **Route Lines**: Colored lines showing optimized paths for each vehicle
- **Interactive Popups**: Detailed information for each stop
- **Legend**: Color-coded vehicle identification and stop type explanations
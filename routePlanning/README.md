# Dynamic Route Optimizer

An intelligent vehicle route optimization system using Amazon Location Service and DynamoDB for ride-sharing applications with environmental impact tracking.

## Features

### Core Optimization
- **Smart Route Optimization**: Optimal pickup/dropoff sequencing prioritizing passenger journey time
- **Multi-Vehicle Assignment**: Intelligent request distribution across vehicle fleet (up to 20 requests per vehicle)
- **Time-Based Constraints**: Configurable waiting time (15 min default) and travel duration limits (20 min default)
- **Environmental Impact**: Real-time fuel consumption and CO2 emissions tracking
- **Stop Reuse Efficiency**: Bonus for shared pickup/dropoff locations

### Interactive Web Interface
- **Dynamic Time Filtering**: Filter requests by pickup time with default 7am-7pm window
- **Vehicle Visibility Controls**: Show/hide individual vehicle routes with checkboxes
- **Route Details Modal**: Comprehensive optimization results with environmental metrics
- **Real-Time Map Updates**: Flask web interface with parameter-based filtering
- **Beautiful Visualization**: Interactive Folium maps with numbered stops and actual road geometry

### Advanced Features
- **Fuel Efficiency Optimization**: Cost function considers distance, utilization, and clustering
- **Journey Time Tracking**: Accurate passenger travel time from pickup to dropoff
- **Geographic Clustering**: Rewards for route compactness and stop sharing
- **Error Handling**: Comprehensive error reporting and graceful failure handling

## Architecture

- **Backend**: Python Flask server with advanced route optimization algorithms
- **Frontend**: Dynamic Folium-generated HTML maps with interactive controls
- **Database**: DynamoDB tables (requests, stops, vehicles) with datetime handling
- **Routing**: Amazon Location Service for real road network calculations
- **Visualization**: Interactive maps with vehicle toggles and detailed popups

## Files

- `web_server.py` - Flask web application with parameter handling (main entry point)
- `dynamic_route_optimizer.py` - Advanced optimization engine with environmental tracking
- `requirements_web.txt` - Python dependencies (Flask, Boto3, Folium)
- `README.md` - This documentation
- `.gitignore` - Git ignore configuration

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements_web.txt
   ```

2. **Configure AWS credentials and DynamoDB tables:**
   - `requests` table (requestId, originStopId, destStopId, requestedPickupAt)
   - `stops` table (stop_id, stop_lat, stop_lon)
   - `vehicles` table (vehicleId, capacity, latitude, longitude)

3. **Set up Amazon Location Service:**
   - Create route calculator named `MyRouteCalculator`
   - Ensure proper IAM permissions for location services

4. **Run the application:**
   ```bash
   python web_server.py
   ```

5. **Open browser at `http://localhost:5000`**

## Usage

### Web Interface Controls
- **Time Filter**: Set start/end times (defaults to 7am-7pm)
- **Waiting Time**: Configure maximum passenger waiting time (5-120 minutes)
- **Travel Duration**: Set maximum route duration (15-180 minutes)
- **Vehicle Toggles**: Show/hide individual vehicle routes in legend
- **Route Details**: Click 📊 button for comprehensive optimization results

### Map Interactions
- **Stop Markers**: Click numbered circles for pickup/dropoff details
- **Vehicle Markers**: Car icons show starting positions
- **Route Lines**: Colored paths show actual road routes
- **Popups**: Detailed information including journey times

## Route Optimization Algorithm

### Cost Function Considers:
1. **Distance to Pickup**: Heavily weighted for fuel efficiency
2. **Route Efficiency**: Penalties for detours and route extensions
3. **Vehicle Utilization**: Bonuses for higher passenger loads
4. **Time Clustering**: Rewards for requests with similar pickup times
5. **Geographic Clustering**: Bonuses for shared bus stops

### Constraints:
- **Waiting Time**: Maximum time between earliest and latest pickups
- **Travel Duration**: Maximum total route time
- **Vehicle Capacity**: Configurable passenger limits
- **Stop Sequence**: Optimized pickup/dropoff ordering

### Environmental Metrics:
- **Fuel Consumption**: 8L/100km assumption for diesel vehicles
- **CO2 Emissions**: 2.31kg CO2 per liter of fuel
- **Per-Passenger Impact**: Efficiency metrics per passenger served

## Map Features

- **Numbered Stops**: Sequential ordering with pickup/dropoff indicators
- **Vehicle Markers**: Color-coded car icons with route identification
- **Route Geometry**: Actual road paths from Amazon Location Service
- **Interactive Legend**: Vehicle toggles and symbol explanations
- **Journey Times**: Accurate passenger travel duration display
- **Environmental Panel**: Optimization objectives and constraints

## Technical Specifications

- **Python 3.8+** with Flask, Boto3, Folium
- **AWS Services**: DynamoDB, Amazon Location Service
- **Route Limits**: 23 waypoints maximum per vehicle (AWS limitation)
- **Coordinate System**: [longitude, latitude] format for AWS compatibility
- **Time Format**: 'YYYY-MM-DD HH:MM:SS' string format in DynamoDB